/**
 * ENV-ROVER 3D - Fully Fixed Edition
 * 
 * Changes made:
 * - Easier levels (6, 8, 10, 12, 15) with MORE waste spawned than needed
 * - Arrow keys support (WASD + ArrowKeys)
 * - Background music via Web Audio API (no external file needed)
 * - Mobile/touch controls
 * - F5 issue fixed - using V key AND shape button for view toggle
 * - Click + E key for collecting waste
 * - Collapsible controls and stats with shape logo buttons
 * - Minimap showing rover and waste positions
 * - Proper waste placement on walkable terrain
 * - Dear Old Dad font used throughout
 * - Updated GitHub link: https://github.com/vstechno-official/env-rover
 * - Added contact email: salaskarvedant66@gmail.com
 * 
 * Let's make this GOATED 🔥
 */

const CONFIG = {
    MOVE_SPEED: 22,
    MOUSE_SENSITIVITY: 0.002,
    JUMP_FORCE: 14,
    GRAVITY: 40,
    FRICTION: 0.88,
    ACCELERATION: 80,
    BATTERY_DRAIN: 0.6,
    BATTERY_RECHARGE: 0.4,
    SOLAR_BOOST: 35,
    COLLECTION_RANGE: 14,
    WASTE_SPAWN_MULTIPLIER: 2.0, // Spawn 2x more waste than needed
    WASTE_TYPES: {
        plastic: { color: 0xff4757, points: 15, icon: '🥤', name: 'Plastic Bottle' },
        paper: { color: 0x2ed573, points: 8, icon: '📄', name: 'Paper Waste' },
        metal: { color: 0xffa502, points: 12, icon: '🥫', name: 'Metal Can' },
        organic: { color: 0x7bed9f, points: 5, icon: '🍂', name: 'Organic Waste' },
        ewaste: { color: 0xa29bfe, points: 25, icon: '🔋', name: 'E-Waste' }
    },
    LEVELS: [
        { name: 'Urban Park', wasteCount: 6, terrain: 'grass', time: 120 },
        { name: 'Beach Cleanup', wasteCount: 8, terrain: 'sand', time: 150 },
        { name: 'City Streets', wasteCount: 10, terrain: 'stone', time: 180 },
        { name: 'Industrial Zone', wasteCount: 12, terrain: 'industrial', time: 210 },
        { name: 'River Bank', wasteCount: 15, terrain: 'mixed', time: 240 }
    ]
};

let scene, camera, renderer, rover;
let terrainBlocks = [], wasteItems = [], particleSystems = [];
let clouds = [], trees = [];
let clock = new THREE.Clock();
let isPlaying = false, isPaused = false;
let currentLevel = 0;
let score = 0, wasteCollected = 0, battery = 100, timeElapsed = 0;
let wasteBreakdown = { plastic: 0, paper: 0, metal: 0, organic: 0, ewaste: 0 };
let viewMode = 'first';
let yaw = 0, pitch = 0;
let velocity = new THREE.Vector3();
let canJump = true;
let keys = {};
let gameCompleted = false;
let bgmEnabled = true;
let audioCtx = null;
let bgmOscillators = [];
let isMobile = false;

function init() {
    detectMobile();
    setupAudio();
    
    const canvas = document.getElementById('gameCanvas');
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x87ceeb);
    scene.fog = new THREE.Fog(0x87ceeb, 50, 180);
    
    camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 4, 0);
    
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    
    setupLights();
    loadLevel(0);
    setupEvents();
    animate();
}

function detectMobile() {
    isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) 
        || window.innerWidth <= 768;
    
    if (isMobile) {
        document.getElementById('mobileControls').style.display = 'block';
        document.getElementById('mobileActions').style.display = 'flex';
        document.getElementById('instructions').style.display = 'none';
        document.getElementById('viewMode').style.display = 'none';
    }
}

function setupAudio() {
    // Web Audio API generated ambient music
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContext();
    } catch (e) {
        console.log('Web Audio not supported');
        bgmEnabled = false;
    }
}

function playBGM() {
    if (!bgmEnabled || !audioCtx) return;
    if (audioCtx.state === 'suspended') audioCtx.resume();
    if (bgmOscillators.length > 0) return;
    
    // Create ambient pad sound
    const freqs = [196.00, 246.94, 293.66, 349.23]; // G minor-ish chord
    
    freqs.forEach((freq, i) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        const filter = audioCtx.createBiquadFilter();
        
        osc.type = i % 2 === 0 ? 'sine' : 'triangle';
        osc.frequency.value = freq;
        
        filter.type = 'lowpass';
        filter.frequency.value = 600;
        
        gain.gain.value = 0.03;
        
        osc.connect(filter);
        filter.connect(gain);
        gain.connect(audioCtx.destination);
        
        osc.start();
        bgmOscillators.push({ osc, gain });
    });
    
    // Add slow LFO modulation for ambient feel
    setInterval(() => {
        if (!bgmEnabled) return;
        bgmOscillators.forEach((bgm, i) => {
            const time = audioCtx.currentTime;
            bgm.gain.gain.setTargetAtTime(
                0.02 + Math.sin(time * 0.5 + i) * 0.015,
                time,
                0.5
            );
        });
    }, 100);
}

function stopBGM() {
    bgmOscillators.forEach(bgm => {
        try {
            bgm.osc.stop();
            bgm.osc.disconnect();
        } catch (e) {}
    });
    bgmOscillators = [];
}

function toggleBGM() {
    bgmEnabled = !bgmEnabled;
    const btn = document.getElementById('bgmToggle');
    const check = document.getElementById('bgmCheck');
    
    if (bgmEnabled) {
        playBGM();
        btn.classList.add('active');
        if (check) check.checked = true;
    } else {
        stopBGM();
        btn.classList.remove('active');
        if (check) check.checked = false;
    }
    
    showNotification(bgmEnabled ? 'Music On' : 'Music Off', 
                     bgmEnabled ? 'Ambient BGM playing' : 'Ambient BGM muted');
}

function setupLights() {
    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    scene.add(ambient);
    
    const sun = new THREE.DirectionalLight(0xffffff, 0.95);
    sun.position.set(80, 150, 60);
    sun.castShadow = true;
    sun.shadow.mapSize.width = 4096;
    sun.shadow.mapSize.height = 4096;
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far = 300;
    const d = 120;
    sun.shadow.camera.left = -d;
    sun.shadow.camera.right = d;
    sun.shadow.camera.top = d;
    sun.shadow.camera.bottom = -d;
    scene.add(sun);
    
    const hemi = new THREE.HemisphereLight(0x87ceeb, 0x4a6b3c, 0.4);
    scene.add(hemi);
}

function clearScene() {
    terrainBlocks.forEach(b => scene.remove(b));
    terrainBlocks = [];
    wasteItems.forEach(w => scene.remove(w.mesh));
    wasteItems = [];
    particleSystems.forEach(p => scene.remove(p));
    particleSystems = [];
    clouds.forEach(c => scene.remove(c));
    clouds = [];
    trees.forEach(t => scene.remove(t));
    trees = [];
    if (rover) scene.remove(rover);
    while (scene.children.length > 0) scene.remove(scene.children[0]);
    setupLights();
}

function createAestheticRover() {
    rover = new THREE.Group();
    
    const chassisGeo = new THREE.BoxGeometry(2.6, 1.3, 4.2);
    const chassisMat = new THREE.MeshStandardMaterial({ color: 0x4a7c23, roughness: 0.6, metalness: 0.2 });
    const chassis = new THREE.Mesh(chassisGeo, chassisMat);
    chassis.position.y = 1.6;
    chassis.castShadow = true;
    chassis.receiveShadow = true;
    rover.add(chassis);
    
    const stripeGeo = new THREE.BoxGeometry(2.65, 0.15, 4.25);
    const stripeMat = new THREE.MeshStandardMaterial({ color: 0x3d5c1d });
    const stripeTop = new THREE.Mesh(stripeGeo, stripeMat);
    stripeTop.position.y = 2.28;
    rover.add(stripeTop);
    const stripeBottom = new THREE.Mesh(stripeGeo, stripeMat);
    stripeBottom.position.y = 0.92;
    rover.add(stripeBottom);
    
    // Solar panels
    const panelBase = new THREE.Mesh(
        new THREE.BoxGeometry(2.4, 0.15, 3.8),
        new THREE.MeshStandardMaterial({ color: 0x1a1a2e })
    );
    panelBase.position.set(0, 2.4, 0);
    panelBase.castShadow = true;
    rover.add(panelBase);
    
    const cellGeo = new THREE.BoxGeometry(0.5, 0.05, 0.5);
    const cellMat = new THREE.MeshStandardMaterial({
        color: 0x3b2f5a, roughness: 0.2, metalness: 0.8,
        emissive: 0x1a0a3a, emissiveIntensity: 0.3
    });
    for (let x = -0.9; x <= 0.9; x += 0.55) {
        for (let z = -1.6; z <= 1.6; z += 0.55) {
            const cell = new THREE.Mesh(cellGeo, cellMat);
            cell.position.set(x, 2.48, z);
            rover.add(cell);
        }
    }
    
    // Wheels
    const wheelGeo = new THREE.CylinderGeometry(0.75, 0.75, 0.5, 24);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x1e1e1e, roughness: 0.95 });
    const wheelPos = [
        [-1.6, 0.6, 1.4], [1.6, 0.6, 1.4],
        [-1.6, 0.6, -1.4], [1.6, 0.6, -1.4]
    ];
    wheelPos.forEach(pos => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(...pos);
        wheel.castShadow = true;
        rover.add(wheel);
        
        const hub = new THREE.Mesh(
            new THREE.CylinderGeometry(0.35, 0.35, 0.55, 12),
            new THREE.MeshStandardMaterial({ color: 0x4a4a4a, metalness: 0.5 })
        );
        hub.rotation.z = Math.PI / 2;
        hub.position.set(pos[0] > 0 ? pos[0] - 0.05 : pos[0] + 0.05, 0.6, pos[2]);
        rover.add(hub);
        
        const spring = new THREE.Mesh(
            new THREE.CylinderGeometry(0.12, 0.12, 0.8, 8),
            new THREE.MeshStandardMaterial({ color: 0x666666, metalness: 0.7 })
        );
        spring.position.set(pos[0], 1.35, pos[2]);
        rover.add(spring);
    });
    
    // Fenders
    const fenderGeo = new THREE.BoxGeometry(0.6, 0.4, 2);
    const fenderMat = new THREE.MeshStandardMaterial({ color: 0x3d5c1d });
    const leftFender = new THREE.Mesh(fenderGeo, fenderMat);
    leftFender.position.set(-1.5, 2.05, 0);
    leftFender.castShadow = true;
    rover.add(leftFender);
    const rightFender = new THREE.Mesh(fenderGeo, fenderMat);
    rightFender.position.set(1.5, 2.05, 0);
    rightFender.castShadow = true;
    rover.add(rightFender);
    
    // Mast
    const metalMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.7 });
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.12, 2.2, 8), metalMat);
    mast.position.set(0, 3.8, 1);
    mast.castShadow = true;
    rover.add(mast);
    
    const head = new THREE.Mesh(
        new THREE.BoxGeometry(0.7, 0.45, 0.4),
        new THREE.MeshStandardMaterial({ color: 0x2a2a2a, metalness: 0.5 })
    );
    head.position.set(0, 5.0, 1);
    head.castShadow = true;
    rover.add(head);
    
    const lensMat = new THREE.MeshStandardMaterial({ color: 0x111144, emissive: 0x3333ff, emissiveIntensity: 0.8 });
    const leftLens = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.15, 12), lensMat);
    leftLens.rotation.x = Math.PI / 2;
    leftLens.position.set(-0.2, 5.0, 1.22);
    rover.add(leftLens);
    const rightLens = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.15, 12), lensMat);
    rightLens.rotation.x = Math.PI / 2;
    rightLens.position.set(0.2, 5.0, 1.22);
    rover.add(rightLens);
    
    // Robotic arm
    const armGroup = new THREE.Group();
    armGroup.position.set(1.4, 2, 0.6);
    const armMetalMat = new THREE.MeshStandardMaterial({ color: 0x7a7a7a, metalness: 0.6 });
    const shoulderMat = new THREE.MeshStandardMaterial({ color: 0x5a5a5a, metalness: 0.6 });
    
    const shoulder = new THREE.Mesh(new THREE.SphereGeometry(0.25, 16, 16), shoulderMat);
    armGroup.add(shoulder);
    
    const upperArm = new THREE.Mesh(new THREE.BoxGeometry(0.18, 1.3, 0.18), armMetalMat);
    upperArm.position.set(0, 0.65, 0);
    upperArm.castShadow = true;
    armGroup.add(upperArm);
    
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.2, 16, 16), shoulderMat);
    elbow.position.set(0, 1.3, 0);
    armGroup.add(elbow);
    
    const forearm = new THREE.Mesh(new THREE.BoxGeometry(0.14, 1.1, 0.14), armMetalMat);
    forearm.position.set(0, 1.9, 0.3);
    forearm.rotation.x = -0.5;
    forearm.castShadow = true;
    armGroup.add(forearm);
    
    const clawGroup = new THREE.Group();
    clawGroup.position.set(0, 2.45, 0.55);
    const palm = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.25, 0.3), shoulderMat);
    clawGroup.add(palm);
    const fingerGeo = new THREE.BoxGeometry(0.08, 0.5, 0.12);
    const f1 = new THREE.Mesh(fingerGeo, armMetalMat);
    f1.position.set(-0.12, 0.35, 0); f1.rotation.x = 0.3;
    clawGroup.add(f1);
    const f2 = new THREE.Mesh(fingerGeo, armMetalMat);
    f2.position.set(0.12, 0.35, 0); f2.rotation.x = 0.3;
    clawGroup.add(f2);
    const f3 = new THREE.Mesh(fingerGeo, armMetalMat);
    f3.position.set(0, 0.35, -0.12); f3.rotation.x = -0.3;
    clawGroup.add(f3);
    armGroup.add(clawGroup);
    rover.add(armGroup);
    rover.userData.arm = armGroup;
    
    // Collection bin
    const binFrame = new THREE.Mesh(
        new THREE.BoxGeometry(2.2, 1.8, 1.5),
        new THREE.MeshStandardMaterial({ color: 0x6a6a5a, metalness: 0.4, transparent: true, opacity: 0.3 })
    );
    binFrame.position.set(0, 1.6, 2.5);
    binFrame.castShadow = true;
    rover.add(binFrame);
    
    // Antenna
    const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.5, 6), metalMat);
    ant.position.set(-0.8, 3.5, -1.8);
    rover.add(ant);
    const antTip = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 8), new THREE.MeshBasicMaterial({ color: 0xff0000 }));
    antTip.position.set(-0.8, 4.3, -1.8);
    rover.add(antTip);
    rover.userData.antTip = antTip;
    
    // LED
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 12), new THREE.MeshBasicMaterial({ color: 0x00ff00 }));
    led.position.set(0, 2.0, 2.15);
    rover.add(led);
    rover.userData.led = led;
    
    scene.add(rover);
}

function createMinecraftTerrain() {
    terrainBlocks.forEach(b => scene.remove(b));
    terrainBlocks = [];
    trees.forEach(t => scene.remove(t));
    trees = [];
    
    const level = CONFIG.LEVELS[currentLevel];
    let terrainType = level.terrain;
    
    const blockSize = 5;
    const worldSize = 24;
    const boxGeo = new THREE.BoxGeometry(blockSize, blockSize, blockSize);
    
    const materials = {
        grass: createBlockMaterials(0x5c8a45, 0x5c8a45, 0x7bc955, 0x4a3c2a, 0x5c8a45, 0x5c8a45),
        dirt: createBlockMaterials(0x4a3c2a),
        sand: createBlockMaterials(0xd4c48a, 0xd4c48a, 0xe6d59c, 0xb0a070, 0xd4c48a, 0xd4c48a),
        stone: createBlockMaterials(0x808080),
        industrial: createBlockMaterials(0x555555, 0x555555, 0x666666, 0x333333, 0x555555, 0x555555),
        water: createBlockMaterials(0x3498db, 0x3498db, 0x5dade2, 0x2e86c1, 0x3498db, 0x3498db)
    };
    
    function getHeight(x, z) {
        let h = Math.sin(x * 0.25) * Math.cos(z * 0.25) * 1.5;
        h += Math.sin(x * 0.6 + z * 0.4) * 0.6;
        h += Math.cos(x * 0.9) * Math.sin(z * 0.9) * 0.3;
        return Math.floor(h);
    }
    
    const baseMat = terrainType === 'mixed' ? materials.grass : (materials[terrainType] || materials.grass);
    
    for (let x = -worldSize/2; x < worldSize/2; x++) {
        for (let z = -worldSize/2; z < worldSize/2; z++) {
            const height = getHeight(x, z);
            const y = height * blockSize;
            
            let mat = baseMat;
            if (terrainType === 'mixed') {
                const noise = Math.sin(x * 0.5) + Math.cos(z * 0.5);
                if (noise > 0.8) mat = materials.sand;
                else if (noise < -0.8) mat = materials.stone;
                else mat = materials.grass;
            }
            
            const block = new THREE.Mesh(boxGeo, mat);
            block.position.set(x * blockSize, y, z * blockSize);
            block.receiveShadow = true;
            block.castShadow = true;
            scene.add(block);
            terrainBlocks.push(block);
            
            for (let d = 1; d <= 3; d++) {
                const fill = new THREE.Mesh(boxGeo, materials.dirt);
                fill.position.set(x * blockSize, y - d * blockSize, z * blockSize);
                fill.receiveShadow = true;
                scene.add(fill);
                terrainBlocks.push(fill);
            }
        }
    }
    
    if (terrainType === 'mixed') {
        for (let x = worldSize/2 - 4; x < worldSize/2; x++) {
            for (let z = -worldSize/2; z < worldSize/2; z++) {
                const height = getHeight(x, z);
                const y = height * blockSize - blockSize/2;
                const water = new THREE.Mesh(
                    new THREE.BoxGeometry(blockSize, blockSize * 0.7, blockSize),
                    new THREE.MeshStandardMaterial({ color: 0x3498db, transparent: true, opacity: 0.7, roughness: 0.1 })
                );
                water.position.set(x * blockSize, y, z * blockSize);
                scene.add(water);
                terrainBlocks.push(water);
            }
        }
    }
    
    addStructures(terrainType, materials, blockSize);
    addTrees(materials, blockSize);
    addClouds();
}

function createBlockMaterials(right, left, top, bottom, front, back) {
    if (arguments.length === 1) {
        return new THREE.MeshStandardMaterial({ color: right, roughness: 0.9 });
    }
    return [
        new THREE.MeshStandardMaterial({ color: right, roughness: 0.9 }),
        new THREE.MeshStandardMaterial({ color: left, roughness: 0.9 }),
        new THREE.MeshStandardMaterial({ color: top, roughness: 0.9 }),
        new THREE.MeshStandardMaterial({ color: bottom, roughness: 0.9 }),
        new THREE.MeshStandardMaterial({ color: front, roughness: 0.9 }),
        new THREE.MeshStandardMaterial({ color: back, roughness: 0.9 })
    ];
}

function addStructures(terrainType, materials, blockSize) {
    const structureCount = 10;
    const boxGeo = new THREE.BoxGeometry(blockSize, blockSize, blockSize);
    
    for (let i = 0; i < structureCount; i++) {
        const x = Math.floor((Math.random() - 0.5) * 16);
        const z = Math.floor((Math.random() - 0.5) * 16);
        if (Math.sqrt(x*x + z*z) < 5) continue;
        
        const height = Math.floor(Math.random() * 3) + 1;
        const mat = Math.random() > 0.5 ? (materials[terrainType] || materials.stone) : materials.stone;
        const h = getTerrainHeightAt(x, z) * blockSize + blockSize/2;
        
        for (let hLevel = 0; hLevel < height; hLevel++) {
            const block = new THREE.Mesh(boxGeo, mat);
            block.position.set(x * blockSize, h + hLevel * blockSize, z * blockSize);
            block.castShadow = true;
            block.receiveShadow = true;
            scene.add(block);
            terrainBlocks.push(block);
        }
    }
}

function addTrees(materials, blockSize) {
    const treeCount = 8;
    for (let i = 0; i < treeCount; i++) {
        const x = Math.floor((Math.random() - 0.5) * 16);
        const z = Math.floor((Math.random() - 0.5) * 16);
        if (Math.sqrt(x*x + z*z) < 7) continue;
        
        const h = getTerrainHeightAt(x, z) * blockSize;
        
        const trunk = new THREE.Mesh(
            new THREE.BoxGeometry(1.5, 6, 1.5),
            new THREE.MeshStandardMaterial({ color: 0x5c4033 })
        );
        trunk.position.set(x * blockSize, h + 3, z * blockSize);
        trunk.castShadow = true;
        scene.add(trunk);
        trees.push(trunk);
        
        const leaves = new THREE.Mesh(
            new THREE.BoxGeometry(6, 5, 6),
            new THREE.MeshStandardMaterial({ color: 0x2d5a27 })
        );
        leaves.position.set(x * blockSize, h + 8, z * blockSize);
        leaves.castShadow = true;
        scene.add(leaves);
        trees.push(leaves);
        
        const sideLeaf = new THREE.Mesh(
            new THREE.BoxGeometry(3, 2, 3),
            new THREE.MeshStandardMaterial({ color: 0x2d5a27 })
        );
        sideLeaf.position.set(x * blockSize, h + 11, z * blockSize);
        sideLeaf.castShadow = true;
        scene.add(sideLeaf);
        trees.push(sideLeaf);
    }
}

function addClouds() {
    const cloudMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 });
    const cloudGeo = new THREE.BoxGeometry(8, 4, 6);
    
    for (let i = 0; i < 12; i++) {
        const cloud = new THREE.Group();
        const parts = Math.floor(Math.random() * 3) + 2;
        for (let j = 0; j < parts; j++) {
            const part = new THREE.Mesh(cloudGeo, cloudMat);
            part.position.set(j * 5 + (Math.random() - 0.5) * 3, (Math.random() - 0.5) * 2, (Math.random() - 0.5) * 4);
            cloud.add(part);
        }
        cloud.position.set((Math.random() - 0.5) * 180, 60 + Math.random() * 20, (Math.random() - 0.5) * 180);
        cloud.userData = { speed: 2 + Math.random() * 3 };
        scene.add(cloud);
        clouds.push(cloud);
    }
}

function getTerrainHeightAt(x, z) {
    let h = Math.sin(x * 0.25) * Math.cos(z * 0.25) * 1.5;
    h += Math.sin(x * 0.6 + z * 0.4) * 0.6;
    h += Math.cos(x * 0.9) * Math.sin(z * 0.9) * 0.3;
    return Math.floor(h);
}

function getRandomSpawnPosition(minDist = 15, maxDist = 55) {
    const angle = Math.random() * Math.PI * 2;
    const dist = minDist + Math.random() * (maxDist - minDist);
    return {
        x: Math.cos(angle) * dist,
        z: Math.sin(angle) * dist
    };
}

function createWaste() {
    wasteItems.forEach(w => scene.remove(w.mesh));
    wasteItems = [];
    
    const level = CONFIG.LEVELS[currentLevel];
    const wasteTypes = Object.keys(CONFIG.WASTE_TYPES);
    const blockSize = 5;
    
    // Spawn MORE waste than needed
    const spawnCount = Math.floor(level.wasteCount * CONFIG.WASTE_SPAWN_MULTIPLIER);
    
    for (let i = 0; i < spawnCount; i++) {
        const type = wasteTypes[Math.floor(Math.random() * wasteTypes.length)];
        const config = CONFIG.WASTE_TYPES[type];
        
        // Get random position with clear distance from center
        let attempts = 0;
        let pos;
        do {
            pos = getRandomSpawnPosition(12, 45);
            attempts++;
        } while (attempts < 30);
        
        const gx = Math.round(pos.x / blockSize);
        const gz = Math.round(pos.z / blockSize);
        const height = getTerrainHeightAt(gx, gz) * blockSize + blockSize/2 + 3;
        
        // Avoid spawning inside structures (simple check)
        const tooCloseToStructure = terrainBlocks.some(b => {
            const dx = b.position.x - pos.x;
            const dz = b.position.z - pos.z;
            const dy = b.position.y - height;
            return Math.abs(dx) < 3 && Math.abs(dz) < 3 && Math.abs(dy) < 5 && b.position.y > 0;
        });
        
        if (tooCloseToStructure) {
            i--; continue;
        }
        
        const group = new THREE.Group();
        
        const cubeGeo = new THREE.BoxGeometry(1.4, 1.4, 1.4);
        const cubeMat = new THREE.MeshStandardMaterial({
            color: config.color,
            emissive: config.color,
            emissiveIntensity: 0.5,
            roughness: 0.2,
            metalness: 0.8,
            transparent: true,
            opacity: 0.95
        });
        const cube = new THREE.Mesh(cubeGeo, cubeMat);
        cube.castShadow = true;
        group.add(cube);
        
        const frameGeo = new THREE.BoxGeometry(1.7, 1.7, 1.7);
        const frameMat = new THREE.MeshBasicMaterial({ color: config.color, wireframe: true, transparent: true, opacity: 0.6 });
        const frame = new THREE.Mesh(frameGeo, frameMat);
        group.add(frame);
        
        // Floating icon above waste (so it's easier to spot)
        const spriteCanvas = document.createElement('canvas');
        spriteCanvas.width = 64;
        spriteCanvas.height = 64;
        const ctx = spriteCanvas.getContext('2d');
        ctx.font = '48px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(config.icon, 32, 32);
        const texture = new THREE.CanvasTexture(spriteCanvas);
        const spriteMat = new THREE.SpriteMaterial({ map: texture });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.set(0, 2.2, 0);
        sprite.scale.set(2.5, 2.5, 2.5);
        group.add(sprite);
        
        const light = new THREE.PointLight(config.color, 1.5, 12);
        group.add(light);
        
        group.position.set(pos.x, height, pos.z);
        scene.add(group);
        
        wasteItems.push({
            mesh: group,
            type,
            collected: false,
            offset: Math.random() * Math.PI * 2
        });
    }
}

function loadLevel(levelIndex) {
    currentLevel = levelIndex;
    const level = CONFIG.LEVELS[levelIndex];
    
    document.getElementById('levelIndicator').innerHTML = 
        `Level: <span>${levelIndex + 1}</span> - ${level.name}`;
    
    if (levelIndex === 0) {
        score = 0;
        wasteCollected = 0;
        timeElapsed = 0;
        battery = 100;
        wasteBreakdown = { plastic: 0, paper: 0, metal: 0, organic: 0, ewaste: 0 };
    }
    
    clearScene();
    createMinecraftTerrain();
    createAestheticRover();
    createWaste();
    
    yaw = 0;
    pitch = 0;
    velocity.set(0, 0, 0);
    canJump = false;
    
    setTimeout(() => {
        if (rover) rover.position.set(0, 15, 0);
    }, 50);
    
    updateUI();
    updateMinimap();
    showNotification(`Level ${levelIndex + 1}: ${level.name}`,
                     `Find and collect ${level.wasteCount} waste items`);
}

function setupEvents() {
    document.addEventListener('keydown', (e) => {
        keys[e.code] = true;
        
        if (e.code === 'Space' && canJump && isPlaying && !isPaused) {
            velocity.y = CONFIG.JUMP_FORCE;
            canJump = false;
        }
        
        if (e.code === 'KeyB' && isPlaying && !isPaused) {
            activateSolarBoost();
        }
        
        if ((e.code === 'KeyE') && isPlaying && !isPaused) {
            collectWaste();
        }
        
        if ((e.code === 'F5' || e.code === 'KeyV') && isPlaying && !isPaused) {
            e.preventDefault();
            toggleViewMode();
        }
        
        if (e.code === 'Escape' && isPlaying) {
            e.preventDefault();
            if (document.getElementById('certificateModal').style.display === 'flex') return;
            togglePause();
        }
    });
    
    document.addEventListener('keyup', (e) => {
        keys[e.code] = false;
    });
    
    document.addEventListener('mousemove', (e) => {
        if (isPlaying && !isPaused && document.pointerLockElement) {
            yaw -= e.movementX * CONFIG.MOUSE_SENSITIVITY;
            pitch -= e.movementY * CONFIG.MOUSE_SENSITIVITY;
            pitch = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, pitch));
        }
    });
    
    document.addEventListener('pointerlockchange', () => {
        if (!document.pointerLockElement && isPlaying && !isPaused) {
            if (document.getElementById('certificateModal').style.display !== 'flex') {
                togglePause();
            }
        }
    });
    
    // Menu buttons
    document.getElementById('startBtn').addEventListener('click', startGame);
    document.getElementById('creditsBtn').addEventListener('click', () => {
        alert('ENV-ROVER 3D\n\nDeveloped by the ENV-ROVER Team\nConcept & Idea: Vedant V Salaskar\n\nGitHub: https://github.com/vstechno-official/env-rover\nEmail: salaskarvedant66@gmail.com\n\nInspired by NASA Perseverance, Minecraft & OpenAI Swarm\nFor a cleaner India 🇮🇳');
    });
    
    document.getElementById('downloadCert').addEventListener('click', downloadCertificate);
    document.getElementById('closeCert').addEventListener('click', () => {
        document.getElementById('certificateModal').style.display = 'none';
        quitToMenu();
    });
    
    // Shape buttons
    document.getElementById('controlsToggle').addEventListener('click', () => {
        const el = document.getElementById('instructions');
        el.classList.toggle('hidden');
        document.getElementById('controlsToggle').classList.toggle('active');
    });
    
    document.getElementById('statsToggle').addEventListener('click', () => {
        const el = document.getElementById('scorePanel');
        el.classList.toggle('hidden');
        document.getElementById('statsToggle').classList.toggle('active');
    });
    
    document.getElementById('bgmToggle').addEventListener('click', toggleBGM);
    document.getElementById('viewToggle').addEventListener('click', () => {
        if (isPlaying) toggleViewMode();
    });
    
    document.getElementById('bgmCheck').addEventListener('change', (e) => {
        bgmEnabled = e.target.checked;
        if (bgmEnabled) playBGM(); else stopBGM();
    });
    
    // Pause buttons
    document.getElementById('resumeButton').addEventListener('click', togglePause);
    document.getElementById('restartButton').addEventListener('click', () => {
        isPaused = false;
        document.getElementById('pauseMenu').style.display = 'none';
        loadLevel(currentLevel);
        requestPointerLock();
    });
    document.getElementById('quitButton').addEventListener('click', quitToMenu);
    
    // Collect on click
    document.addEventListener('mousedown', (e) => {
        if (e.button === 0 && isPlaying && !isPaused && document.pointerLockElement) {
            collectWaste();
        }
    });
    
    // Mobile controls
    setupMobileControls();
    
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });
}

function setupMobileControls() {
    const setupBtn = (id, code) => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.addEventListener('touchstart', (e) => { e.preventDefault(); keys[code] = true; });
        btn.addEventListener('touchend', (e) => { e.preventDefault(); keys[code] = false; });
        btn.addEventListener('mousedown', (e) => { e.preventDefault(); keys[code] = true; });
        btn.addEventListener('mouseup', (e) => { e.preventDefault(); keys[code] = false; });
        btn.addEventListener('mouseleave', (e) => { e.preventDefault(); keys[code] = false; });
    };
    
    setupBtn('mb-up', 'ArrowUp');
    setupBtn('mb-down', 'ArrowDown');
    setupBtn('mb-left', 'ArrowLeft');
    setupBtn('mb-right', 'ArrowRight');
    
    // Mobile collect
    const collectBtn = document.getElementById('mb-collect');
    collectBtn.addEventListener('touchstart', (e) => { e.preventDefault(); collectWaste(); });
    collectBtn.addEventListener('click', (e) => { e.preventDefault(); if (isPlaying) collectWaste(); });
    
    // Mobile boost
    const boostBtn = document.getElementById('mb-boost');
    boostBtn.addEventListener('touchstart', (e) => { e.preventDefault(); activateSolarBoost(); });
    boostBtn.addEventListener('click', (e) => { e.preventDefault(); if (isPlaying) activateSolarBoost(); });
    
    // Mobile jump
    const jumpBtn = document.getElementById('mb-jump');
    jumpBtn.addEventListener('touchstart', (e) => {
        e.preventDefault();
        if (canJump) { velocity.y = CONFIG.JUMP_FORCE; canJump = false; }
    });
}

function startGame() {
    document.getElementById('mainMenu').style.display = 'none';
    isPlaying = true;
    isPaused = false;
    loadLevel(0);
    
    if (bgmEnabled) playBGM();
    if (!isMobile) requestPointerLock();
    
    showNotification('Mission Started!', 'Find and collect glowing waste cubes');
    showEnvMessage('🌱 "Every piece of waste collected is a step towards a cleaner India."');
}

function requestPointerLock() {
    const canvas = document.getElementById('gameCanvas');
    if (canvas.requestPointerLock && !isMobile) {
        canvas.requestPointerLock().catch(err => console.log('Pointer lock failed:', err));
    }
}

function togglePause() {
    if (!isPlaying) return;
    isPaused = !isPaused;
    const pauseMenu = document.getElementById('pauseMenu');
    
    if (isPaused) {
        pauseMenu.style.display = 'flex';
        if (!isMobile) document.exitPointerLock();
    } else {
        pauseMenu.style.display = 'none';
        if (!isMobile) requestPointerLock();
        clock.getDelta();
    }
}

function toggleViewMode() {
    viewMode = viewMode === 'first' ? 'third' : 'first';
    document.getElementById('viewMode').textContent = 
        viewMode === 'first' ? 'V: First Person' : 'V: Third Person';
    showNotification(viewMode === 'first' ? 'First Person View' : 'Third Person View',
                     `Camera switched to ${viewMode} person`);
}

function activateSolarBoost() {
    if (battery >= 100) {
        showNotification('Battery Full!', 'No boost needed');
        return;
    }
    battery = Math.min(100, battery + CONFIG.SOLAR_BOOST);
    showNotification('☀️ Solar Boost!', `+${CONFIG.SOLAR_BOOST}% Battery`);
    
    const flash = new THREE.PointLight(0xffff00, 4, 60);
    flash.position.copy(rover.position);
    flash.position.y += 6;
    scene.add(flash);
    setTimeout(() => scene.remove(flash), 800);
}

function collectWaste() {
    let collected = false;
    const checkPos = rover.position.clone();
    checkPos.y += 3.5;
    
    wasteItems.forEach(item => {
        if (item.collected) return;
        
        const dist = checkPos.distanceTo(item.mesh.position);
        
        if (dist < CONFIG.COLLECTION_RANGE) {
            item.collected = true;
            collected = true;
            
            const config = CONFIG.WASTE_TYPES[item.type];
            score += config.points;
            wasteCollected++;
            wasteBreakdown[item.type]++;
            
            spawnParticles(item.mesh.position, config.color);
            scene.remove(item.mesh);
            
            showNotification(`+${config.points} pts`, `${config.name} collected!`);
        }
    });
    
    checkLevelCompletion();
    updateUI();
    updateMinimap();
}

function spawnParticles(position, color) {
    const count = 25;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    const velocities = [];
    
    for (let i = 0; i < count; i++) {
        positions[i*3] = position.x;
        positions[i*3+1] = position.y;
        positions[i*3+2] = position.z;
        velocities.push({
            x: (Math.random() - 0.5) * 14,
            y: Math.random() * 14,
            z: (Math.random() - 0.5) * 14
        });
    }
    
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.PointsMaterial({ color: color, size: 0.6, transparent: true, opacity: 1 });
    const particles = new THREE.Points(geo, mat);
    particles.userData = { velocities, age: 0, maxAge: 1.5 };
    scene.add(particles);
    particleSystems.push(particles);
}

function checkLevelCompletion() {
    const level = CONFIG.LEVELS[currentLevel];
    const remaining = level.wasteCount - wasteItems.filter(item => item.collected).length;
    
    if (remaining <= 0) {
        setTimeout(() => {
            currentLevel++;
            if (currentLevel >= CONFIG.LEVELS.length) {
                gameCompleted = true;
                showNotification('🏆 MISSION ACCOMPLISHED!', 'All areas cleaned!');
                if (!isMobile) document.exitPointerLock();
                setTimeout(showCertificateModal, 2000);
            } else {
                showNotification('Level Complete!', 'Moving to next area...');
                setTimeout(() => loadLevel(currentLevel), 2000);
            }
        }, 800);
    }
}

function showCertificateModal() {
    document.getElementById('certificateModal').style.display = 'flex';
    if (!isMobile) document.exitPointerLock();
    showEnvMessage('🌍 "You are now an ENV-ROVER Environmental Ambassador!"');
}

function downloadCertificate() {
    const name = document.getElementById('certName').value.trim() || 'ENV-ROVER Player';
    const date = new Date().toLocaleDateString();
    
    try {
        const { jsPDF } = window.jspdf;
        const doc = new jsPDF('landscape');
        
        doc.setDrawColor(233, 69, 96);
        doc.setLineWidth(5);
        doc.rect(10, 10, 277, 180);
        
        doc.setDrawColor(78, 205, 196);
        doc.setLineWidth(2);
        doc.rect(18, 18, 261, 164);
        
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(28);
        doc.setTextColor(233, 69, 96);
        doc.text('CERTIFICATE OF ENVIRONMENTAL AWARENESS', 148.5, 48, { align: 'center' });
        
        doc.setFontSize(18);
        doc.setTextColor(74, 124, 35);
        doc.text('ENV-ROVER Clean Earth Mission', 148.5, 64, { align: 'center' });
        
        doc.setFontSize(15);
        doc.setTextColor(0, 0, 0);
        doc.setFont('helvetica', 'normal');
        const body = `This certifies that\n\n${name}\n\nhas successfully completed the ENV-ROVER 3D Clean Earth Mission,\ndemonstrated understanding of waste segregation and environmental responsibility,\nand pledged to spread awareness for a cleaner planet.`;
        doc.text(body, 148.5, 82, { align: 'center', lineHeightFactor: 1.35 });
        
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(14);
        doc.setTextColor(78, 205, 196);
        doc.text(`Final Score: ${score} | Waste Collected: ${wasteCollected} items | Levels Completed: 5`, 148.5, 141, { align: 'center' });
        
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(12);
        doc.setTextColor(100, 100, 100);
        doc.text(`Date: ${date}`, 40, 158);
        doc.text('ENV-ROVER Team - Concept by Vedant V Salaskar', 148.5, 166, { align: 'center' });
        doc.text('Contact: salaskarvedant66@gmail.com', 148.5, 172, { align: 'center' });
        doc.text('"Every piece of waste collected is a step towards a cleaner India"', 148.5, 178, { align: 'center' });
        
        doc.save('ENV-ROVER-Certificate-of-Awareness.pdf');
        showNotification('Certificate Downloaded!', 'Spread the awareness!');
    } catch (err) {
        console.error('PDF generation failed:', err);
        alert('Certificate could not be generated, sorry!');
    }
}

function quitToMenu() {
    isPlaying = false;
    isPaused = false;
    gameCompleted = false;
    document.getElementById('pauseMenu').style.display = 'none';
    document.getElementById('certificateModal').style.display = 'none';
    document.getElementById('mainMenu').style.display = 'flex';
    if (!isMobile) document.exitPointerLock();
    stopBGM();
    
    score = 0;
    wasteCollected = 0;
    timeElapsed = 0;
    battery = 100;
    viewMode = 'first';
    document.getElementById('viewMode').textContent = 'V: First Person';
    wasteBreakdown = { plastic: 0, paper: 0, metal: 0, organic: 0, ewaste: 0 };
    updateUI();
}

function updatePhysics(delta) {
    if (!isPlaying || isPaused) return;
    
    const forward = (keys['KeyW'] || keys['ArrowUp']) ? 1 : 0;
    const backward = (keys['KeyS'] || keys['ArrowDown']) ? 1 : 0;
    const left = (keys['KeyA'] || keys['ArrowLeft']) ? 1 : 0;
    const right = (keys['KeyD'] || keys['ArrowRight']) ? 1 : 0;
    
    const moveZ = forward - backward;
    const moveX = right - left;
    
    if (moveZ !== 0) {
        velocity.x -= Math.sin(yaw) * moveZ * CONFIG.ACCELERATION * delta;
        velocity.z -= Math.cos(yaw) * moveZ * CONFIG.ACCELERATION * delta;
    }
    if (moveX !== 0) {
        velocity.x -= Math.cos(yaw) * moveX * CONFIG.ACCELERATION * delta;
        velocity.z += Math.sin(yaw) * moveX * CONFIG.ACCELERATION * delta;
    }
    
    const speed = Math.sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
    if (speed > CONFIG.MOVE_SPEED) {
        velocity.x = (velocity.x / speed) * CONFIG.MOVE_SPEED;
        velocity.z = (velocity.z / speed) * CONFIG.MOVE_SPEED;
    }
    
    velocity.x *= CONFIG.FRICTION;
    velocity.z *= CONFIG.FRICTION;
    velocity.y -= CONFIG.GRAVITY * delta;
    
    rover.position.x += velocity.x * delta;
    rover.position.z += velocity.z * delta;
    rover.position.y += velocity.y * delta;
    
    const blockSize = 5;
    const gx = Math.round(rover.position.x / blockSize);
    const gz = Math.round(rover.position.z / blockSize);
    const groundHeight = getTerrainHeightAt(gx, gz) * blockSize + blockSize/2;
    
    if (rover.position.y < groundHeight + 0.75) {
        rover.position.y = groundHeight + 0.75;
        velocity.y = 0;
        canJump = true;
    }
    
    const bound = 50;
    rover.position.x = Math.max(-bound, Math.min(bound, rover.position.x));
    rover.position.z = Math.max(-bound, Math.min(bound, rover.position.z));
    
    rover.rotation.z = -velocity.x * 0.015;
    rover.rotation.x = velocity.z * 0.015;
    
    if (rover.userData.arm) {
        rover.userData.arm.rotation.z = Math.sin(clock.getElapsedTime() * 3) * 0.05;
    }
    if (rover.userData.led) {
        rover.userData.led.material.color.setHex(
            Math.floor(clock.getElapsedTime() * 2) % 2 === 0 ? 0x00ff00 : 0x004400
        );
    }
}

function updateCamera() {
    if (!rover) return;
    camera.rotation.order = 'YXZ';
    
    if (viewMode === 'first') {
        camera.position.copy(rover.position);
        camera.position.y += 4.8;
        camera.position.z += 1.0;
        camera.rotation.y = yaw;
        camera.rotation.x = pitch;
        document.getElementById('crosshair').style.display = 'block';
    } else {
        const distance = 14;
        const height = 9;
        const offset = new THREE.Vector3(
            Math.sin(yaw) * distance,
            height,
            Math.cos(yaw) * distance
        );
        camera.position.copy(rover.position).add(offset);
        camera.lookAt(rover.position.x, rover.position.y + 3, rover.position.z);
        document.getElementById('crosshair').style.display = 'none';
    }
}

function updateMinimap() {
    const canvas = document.getElementById('minimap');
    const ctx = canvas.getContext('2d');
    const size = 180;
    const scale = size / 120; // world size 120
    
    ctx.clearRect(0, 0, size, size);
    
    // Background
    ctx.fillStyle = '#1a3009';
    ctx.fillRect(0, 0, size, size);
    
    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i < size; i += 20) {
        ctx.beginPath();
        ctx.moveTo(i, 0); ctx.lineTo(i, size);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(0, i); ctx.lineTo(size, i);
        ctx.stroke();
    }
    
    // Convert world to minimap coords
    function worldToMap(x, z) {
        return {
            x: size/2 + x * scale,
            y: size/2 - z * scale
        };
    }
    
    // Draw uncollected waste
    wasteItems.forEach(item => {
        if (item.collected) return;
        const pos = worldToMap(item.mesh.position.x, item.mesh.position.z);
        const color = CONFIG.WASTE_TYPES[item.type].color;
        ctx.fillStyle = '#' + new THREE.Color(color).getHexString();
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1;
        ctx.stroke();
    });
    
    // Draw rover
    const roverPos = worldToMap(rover.position.x, rover.position.z);
    ctx.fillStyle = '#e94560';
    ctx.beginPath();
    ctx.arc(roverPos.x, roverPos.y, 6, 0, Math.PI * 2);
    ctx.fill();
    
    // Direction indicator
    const dirLength = 12;
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(roverPos.x, roverPos.y);
    ctx.lineTo(
        roverPos.x - Math.sin(yaw) * dirLength,
        roverPos.y + Math.cos(yaw) * dirLength
    );
    ctx.stroke();
}

function updateWaste(delta, time) {
    wasteItems.forEach(item => {
        if (item.collected) return;
        item.mesh.position.y += Math.sin(time * 3 + item.offset) * 0.012;
        item.mesh.rotation.y += delta * 1.2;
        item.mesh.children[1].rotation.y -= delta * 0.8;
    });
}

function updateParticles(delta) {
    for (let i = particleSystems.length - 1; i >= 0; i--) {
        const ps = particleSystems[i];
        ps.userData.age += delta;
        
        if (ps.userData.age >= ps.userData.maxAge) {
            scene.remove(ps);
            particleSystems.splice(i, 1);
            continue;
        }
        
        const positions = ps.geometry.attributes.position.array;
        const vels = ps.userData.velocities;
        for (let j = 0; j < vels.length; j++) {
            positions[j*3] += vels[j].x * delta;
            positions[j*3+1] += vels[j].y * delta;
            positions[j*3+2] += vels[j].z * delta;
            vels[j].y -= 30 * delta;
            ps.material.opacity = 1 - (ps.userData.age / ps.userData.maxAge);
        }
        ps.geometry.attributes.position.needsUpdate = true;
    }
}

function updateClouds(delta) {
    clouds.forEach(cloud => {
        cloud.position.x += cloud.userData.speed * delta;
        if (cloud.position.x > 120) cloud.position.x = -120;
    });
}

function updateBattery(delta) {
    if (!isPlaying || isPaused) return;
    battery -= CONFIG.BATTERY_DRAIN * delta;
    battery += CONFIG.BATTERY_RECHARGE * delta;
    battery = Math.max(0, Math.min(100, battery));
    
    if (battery <= 0) {
        showNotification('⚠️ Battery Depleted!', 'Mission Failed');
        if (!isMobile) document.exitPointerLock();
        isPlaying = false;
        document.getElementById('mainMenu').style.display = 'flex';
    }
}

function updateUI() {
    document.getElementById('totalScore').textContent = score;
    document.getElementById('plasticCount').textContent = wasteBreakdown.plastic;
    document.getElementById('paperCount').textContent = wasteBreakdown.paper;
    document.getElementById('metalCount').textContent = wasteBreakdown.metal;
    document.getElementById('organicCount').textContent = wasteBreakdown.organic;
    document.getElementById('ewasteCount').textContent = wasteBreakdown.ewaste;
    
    document.getElementById('hotbar-plastic').textContent = wasteBreakdown.plastic;
    document.getElementById('hotbar-paper').textContent = wasteBreakdown.paper;
    document.getElementById('hotbar-metal').textContent = wasteBreakdown.metal;
    document.getElementById('hotbar-organic').textContent = wasteBreakdown.organic;
    document.getElementById('hotbar-ewaste').textContent = wasteBreakdown.ewaste;
    
    document.getElementById('wasteCollected').textContent = wasteCollected;
    const level = CONFIG.LEVELS[currentLevel];
    const remaining = level ? level.wasteCount - wasteItems.filter(item => item.collected).length : 0;
    document.getElementById('wasteRemaining').textContent = Math.max(0, remaining);
    
    const minutes = Math.floor(timeElapsed / 60);
    const seconds = Math.floor(timeElapsed % 60);
    document.getElementById('timeElapsed').textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    
    const fill = document.getElementById('batteryFill');
    const bar = document.getElementById('batteryBar');
    fill.textContent = `🔋 ${Math.round(battery)}%`;
    fill.style.width = `${battery}%`;
    
    bar.className = '';
    if (battery < 20) bar.classList.add('critical');
    else if (battery < 40) bar.classList.add('warning');
}

function showNotification(title, message) {
    const el = document.getElementById('notification');
    document.getElementById('notificationTitle').textContent = title;
    document.getElementById('notificationMessage').textContent = message;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
}

function showEnvMessage(text) {
    const el = document.getElementById('envMessage');
    el.textContent = text;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 6000);
}

function animate() {
    requestAnimationFrame(animate);
    
    const delta = Math.min(clock.getDelta(), 0.1);
    const time = clock.getElapsedTime();
    
    if (isPlaying && !isPaused) {
        timeElapsed += delta;
        updatePhysics(delta);
        updateWaste(delta, time);
        updateParticles(delta);
        updateClouds(delta);
        updateBattery(delta);
        updateUI();
        updateMinimap();
        
        if (Math.random() < 0.0005) {
            const messages = [
                '🌍 "Be the change you wish to see in the world."',
                '♻️ "Reduce, Reuse, Recycle - in that order!"',
                '🌱 "A clean environment is a healthy environment."',
                '💚 "Every piece of trash picked up matters."',
                '🌿 "Nature doesn\'t need us. We need nature."'
            ];
            showEnvMessage(messages[Math.floor(Math.random() * messages.length)]);
        }
    }
    
    updateCamera();
    renderer.render(scene, camera);
}

window.addEventListener('load', init);
