"""3D URDF viewer endpoint — renders the grabette gripper with live joint angles."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["viewer"])

VIEWER_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grabette 3D</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { overflow: hidden; background: #1a1a2e; }
  #container { width: 100vw; height: 100vh; }
  #status {
    position: absolute; bottom: 8px; left: 8px;
    color: #7788aa; font: 11px/1.4 monospace;
    pointer-events: none; user-select: none;
  }
  #loading {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    color: #556688; font: 14px monospace;
  }
</style>
<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
  }
}
</script>
</head>
<body>
<div id="container"></div>
<div id="loading">Loading model...</div>
<div id="status"></div>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import URDFLoader from 'https://cdn.jsdelivr.net/npm/urdf-loader@0.12.6/src/URDFLoader.js';

const container = document.getElementById('container');
const statusEl = document.getElementById('status');
const loadingEl = document.getElementById('loading');

// ── Scene ───────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

const camera = new THREE.PerspectiveCamera(
  45, window.innerWidth / window.innerHeight, 0.001, 10,
);
camera.position.set(0.12, 0.12, 0.18);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

// ── Controls ────────────────────────────────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// ── Lighting ────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.5));

const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
dirLight.position.set(0.3, 0.6, 0.4);
dirLight.castShadow = true;
dirLight.shadow.mapSize.set(1024, 1024);
scene.add(dirLight);

const fillLight = new THREE.DirectionalLight(0x8899bb, 0.3);
fillLight.position.set(-0.4, -0.2, 0.3);
scene.add(fillLight);

// ── Grid ────────────────────────────────────────────────────────────
const grid = new THREE.GridHelper(0.4, 16, 0x334466, 0x222244);
scene.add(grid);

// ── URDF ────────────────────────────────────────────────────────────
const LINK_COLORS = {
  thumb_base:        0x7a8a9a,
  phalanx_1_bottom:  0x4488cc,
  phalanx_2:         0xcc8844,
};

const stlLoader = new STLLoader();
let robot = null;

const urdfLoader = new URDFLoader();
urdfLoader.packages = { grabette_right: '/urdf/grabette_right/' };

urdfLoader.loadMeshCb = (path, manager, onComplete) => {
  stlLoader.load(
    path,
    geometry => {
      geometry.computeVertexNormals();
      const mat = new THREE.MeshPhongMaterial({
        color: 0x888888, specular: 0x333333, shininess: 80,
      });
      const mesh = new THREE.Mesh(geometry, mat);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      onComplete(mesh);
    },
    undefined,
    err => {
      console.warn('Mesh load error:', path, err);
      onComplete(new THREE.Object3D());
    },
  );
};

urdfLoader.load('/urdf/grabette_right/robot.urdf', r => {
  robot = r;
  scene.add(robot);

  // Colour each link
  for (const [name, link] of Object.entries(robot.links)) {
    const col = LINK_COLORS[name] || 0x888888;
    link.traverse(child => {
      if (child.isMesh) {
        child.material = new THREE.MeshPhongMaterial({
          color: col, specular: 0x444444, shininess: 80,
        });
      }
    });
  }

  // Fit camera to model
  const box = new THREE.Box3().setFromObject(robot);
  const center = box.getCenter(new THREE.Vector3());
  controls.target.copy(center);
  controls.update();

  loadingEl.style.display = 'none';
});

// ── Joint angle updates ─────────────────────────────────────────────
// Accept updates via postMessage from parent (Gradio iframe)
window.addEventListener('message', e => {
  if (!robot || !e.data) return;
  const { proximal, distal } = e.data;
  if (proximal !== undefined) robot.setJointValue('proximal', proximal);
  if (distal !== undefined)   robot.setJointValue('distal', distal);
  updateStatus(proximal, distal);
});

// Also self-poll /api/state as fallback (when opened standalone)
let usePostMessage = false;
window.addEventListener('message', () => { usePostMessage = true; }, { once: true });

async function pollState() {
  if (usePostMessage || !robot) return;
  try {
    const resp = await fetch('/api/state');
    const state = await resp.json();
    if (state.angle) {
      robot.setJointValue('proximal', state.angle.angle1);
      robot.setJointValue('distal', state.angle.angle2);
      updateStatus(state.angle.angle1, state.angle.angle2);
    }
  } catch (_) {}
}
setInterval(pollState, 500);

function updateStatus(p, d) {
  if (p === undefined || d === undefined) return;
  const deg = v => (v * 180 / Math.PI).toFixed(1);
  statusEl.textContent = `proximal ${deg(p)}°  distal ${deg(d)}°`;
}

// ── Render loop ─────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();

// ── Resize ──────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
</script>
</body>
</html>
"""


@router.get("/viewer")
async def viewer():
    """Serve the 3D URDF viewer page."""
    return HTMLResponse(content=VIEWER_HTML)
