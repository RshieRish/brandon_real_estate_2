'use client';

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const channels = [
  { name: 'Facebook', color: '#eac469', logo: '/logos/dyson-sphere/facebook-icon-logo-svgrepo-com.svg' },
  { name: 'Homes.com', color: '#eac469', logo: '/logos/dyson-sphere/Homes.com.svg' },
  { name: 'Instagram', color: '#eac469', logo: '/logos/dyson-sphere/instagram-2-1-logo-svgrepo-com.svg' },
  { name: 'LinkedIn', color: '#eac469', logo: '/logos/dyson-sphere/linkedin-svgrepo-com.svg' },
  { name: 'MLS', color: '#eac469', logo: '/logos/dyson-sphere/mls-realtor.svg' },
  { name: 'Realtor.com', color: '#eac469', logo: '/logos/dyson-sphere/realtor_com.svg' },
  { name: 'Trulia', color: '#eac469', icon: 'house' },
  { name: 'Zillow', color: '#eac469', logo: '/logos/dyson-sphere/zillow.svg' },
  { name: 'Local Groups', color: '#eac469', icon: 'users' },
  { name: 'Email', color: '#eac469', icon: 'mail' },
  { name: 'Open Houses', color: '#eac469', icon: 'house' },
  { name: 'Video', color: '#eac469', icon: 'play' },
  { name: 'Flyers', color: '#eac469', icon: 'doc' },
  { name: 'Signage', color: '#eac469', icon: 'sign' },
  { name: 'Networking', color: '#eac469', icon: 'nodes' },
];

export default function MarketingSphere() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (!mountRef.current) return;

    let reqId: number;

    // --- Scene Setup ---
    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(
      50,
      1, // default aspect ratio, updated by oberserver
      0.1,
      1000
    );
    // Placed camera at perfect mathematical sweet spot 65 distance with true Y=0 center
    // Frustum height = 60.6. Sphere height bounded at 53. Guaranteed to fit with ~10% margin.
    camera.position.set(0, 0, 65); 

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.setClearColor(0x000000, 0); // Transparent
    mountRef.current.appendChild(renderer.domElement);

    // --- Controls ---
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.04;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.2; // Calmer global camera rotation
    controls.maxDistance = 120; // Increased from 70 so the camera can legally sit at 80
    controls.minDistance = 15;
    controls.maxPolarAngle = Math.PI / 1.5; // Restrict camera from going underneath
    controls.enableZoom = false; // Usually good to disable zoom for a scrollable webpage

    // --- Lighting ---
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xfff0dd, 1.5);
    dirLight1.position.set(15, 25, 15);
    scene.add(dirLight1);

    // Gold rim light 
    const rimLight = new THREE.DirectionalLight(0xeac469, 1.5);
    rimLight.position.set(-20, -10, -20);
    scene.add(rimLight);

    // Central glowing core light
    const pointLight = new THREE.PointLight(0xeac469, 2.5, 40);
    scene.add(pointLight);



    // --- House Loading ---
    const homeGroup = new THREE.Group();
    homeGroup.position.y = -1.5;
    scene.add(homeGroup);

    const loader = new GLTFLoader();
    loader.load(
      '/mini_house.gltf',
      (gltf: unknown) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const uploadedHouse = (gltf as any).scene;
        const box = new THREE.Box3().setFromObject(uploadedHouse);
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        const targetSize = 11;
        const scale = maxDim > 0 ? targetSize / maxDim : 1;
        uploadedHouse.scale.set(scale, scale, scale);

        // Center it
        const scaledBox = new THREE.Box3().setFromObject(uploadedHouse);
        const center = scaledBox.getCenter(new THREE.Vector3());
        uploadedHouse.position.set(-center.x, -center.y - 1, -center.z);

        homeGroup.add(uploadedHouse);
        setLoading(false);
      },
      undefined,
      (err: unknown) => {
        console.error('Error loading gltf:', err);
        setErrorMsg('Failed to load listing model.');
        setLoading(false);
      }
    );

    // --- Constellation Generation ---
    const constellationGroup = new THREE.Group();
    scene.add(constellationGroup);

    // --- Helper: Load SVG to high-res canvas texture (preserves original colors) ---
    function loadLogoTexture(url: string): THREE.CanvasTexture {
      const size = 512;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d')!;
      const texture = new THREE.CanvasTexture(canvas);
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.colorSpace = THREE.SRGBColorSpace; // Preserve original SVG colors!

      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.src = url;
      img.onload = () => {
        // Draw logo centered at full canvas size with padding
        const pad = 40;
        const drawSize = size - pad * 2;
        ctx.drawImage(img, pad, pad, drawSize, drawSize);
        texture.needsUpdate = true;
      };

      return texture;
    }

    // --- Helper: Create icon canvas texture for vector-drawn channels ---
    function createIconCanvas(icon: string, color: string): THREE.CanvasTexture {
      const size = 512;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d')!;

      ctx.fillStyle = color;
      ctx.strokeStyle = color;
      ctx.lineWidth = 14;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      ctx.save();
      ctx.translate(size / 2, size / 2);
      const s = 1.8; // scale up for larger canvas
      ctx.scale(s, s);

      if (icon === 'camera') {
        ctx.strokeRect(-40, -35, 80, 70);
        ctx.beginPath(); ctx.arc(0, 0, 18, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.arc(22, -18, 4, 0, Math.PI * 2); ctx.fill();
      } else if (icon === 'users') {
        ctx.beginPath(); ctx.arc(-15, -15, 15, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.arc(20, -5, 12, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.arc(-15, 40, 25, Math.PI, 0); ctx.stroke();
        ctx.beginPath(); ctx.arc(20, 40, 20, Math.PI, 0); ctx.stroke();
      } else if (icon === 'mail') {
        ctx.strokeRect(-45, -30, 90, 60);
        ctx.beginPath(); ctx.moveTo(-45, -30); ctx.lineTo(0, 5); ctx.lineTo(45, -30); ctx.stroke();
      } else if (icon === 'house') {
        ctx.beginPath(); ctx.moveTo(-40, 40); ctx.lineTo(-40, 0); ctx.lineTo(0, -40); ctx.lineTo(40, 0); ctx.lineTo(40, 40); ctx.closePath(); ctx.stroke();
        ctx.strokeRect(-15, 10, 30, 30);
      } else if (icon === 'play') {
        ctx.beginPath(); ctx.moveTo(-15, -30); ctx.lineTo(30, 0); ctx.lineTo(-15, 30); ctx.closePath(); ctx.stroke(); ctx.fill();
      } else if (icon === 'doc') {
        ctx.strokeRect(-35, -45, 70, 90);
        ctx.beginPath(); ctx.moveTo(-15, -20); ctx.lineTo(15, -20); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(-15, 0); ctx.lineTo(15, 0); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(-15, 20); ctx.lineTo(5, 20); ctx.stroke();
      } else if (icon === 'sign') {
        ctx.beginPath(); ctx.moveTo(0, -40); ctx.lineTo(0, 40); ctx.stroke();
        ctx.fillStyle = color;
        ctx.fillRect(-40, -30, 80, 40);
      } else if (icon === 'nodes') {
        ctx.beginPath(); ctx.arc(0, -20, 10, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(-25, 20, 10, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(25, 20, 10, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.moveTo(0, -20); ctx.lineTo(-25, 20); ctx.lineTo(25, 20); ctx.closePath(); ctx.stroke();
      }
      ctx.restore();

      const texture = new THREE.CanvasTexture(canvas);
      texture.minFilter = THREE.LinearFilter;
      return texture;
    }

    // --- Helper: Create text label sprite ---
    function createTextSprite(text: string) {
      const canvas = document.createElement('canvas');
      canvas.width = 512;
      canvas.height = 128;
      const ctx = canvas.getContext('2d')!;
      ctx.font = '800 42px "Montserrat", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = 'rgba(0,0,0,0.9)';
      ctx.shadowBlur = 12;
      ctx.fillText(text.toUpperCase(), 256, 64);
      const tex = new THREE.CanvasTexture(canvas);
      tex.minFilter = THREE.LinearFilter;
      const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
      const sprite = new THREE.Sprite(mat);
      sprite.scale.set(8, 2, 1);
      return sprite;
    }

    // --- Glass sphere material (Fresnel shader — works with alpha:true renderer) ---
    const glassVertexShader = `
      varying vec3 vNormal;
      varying vec3 vViewPosition;
      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vViewPosition = -mvPosition.xyz;
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * mvPosition;
      }
    `;
    const glassFragmentShader = `
      varying vec3 vNormal;
      varying vec3 vViewPosition;
      uniform vec3 uRimColor;
      uniform float uRimPower;
      uniform float uRimIntensity;
      uniform float uCenterOpacity;
      void main() {
        vec3 viewDir = normalize(vViewPosition);
        float fresnel = pow(1.0 - abs(dot(viewDir, vNormal)), uRimPower);
        // Specular highlight
        vec3 lightDir = normalize(vec3(1.0, 1.0, 1.0));
        vec3 halfDir = normalize(viewDir + lightDir);
        float spec = pow(max(dot(vNormal, halfDir), 0.0), 64.0) * 0.4;
        vec3 color = uRimColor * fresnel * uRimIntensity + vec3(spec);
        float alpha = fresnel * 0.6 + uCenterOpacity + spec * 0.5;
        gl_FragColor = vec4(color, alpha);
      }
    `;
    const glassMaterial = new THREE.ShaderMaterial({
      vertexShader: glassVertexShader,
      fragmentShader: glassFragmentShader,
      uniforms: {
        uRimColor: { value: new THREE.Color(0xeac469) },
        uRimPower: { value: 2.5 },
        uRimIntensity: { value: 1.0 },
        uCenterOpacity: { value: 0.03 },
      },
      transparent: true,
      depthWrite: false,
      side: THREE.FrontSide,
    });
    const glassGeo = new THREE.SphereGeometry(2.8, 32, 32);

    const sphereRadius = 22;
    const nodeGroups: THREE.Group[] = [];

    for (let i = 0; i < channels.length; i++) {
      const phi = Math.acos(-1 + (2 * i) / channels.length);
      const theta = Math.sqrt(channels.length * Math.PI) * phi;

      const x = sphereRadius * Math.cos(theta) * Math.sin(phi);
      const y = sphereRadius * Math.sin(theta) * Math.sin(phi);
      const z = sphereRadius * Math.cos(phi);

      const nodeGroup = new THREE.Group();
      nodeGroup.position.set(x, y, z);

      // 1) Glass sphere — renders AFTER logos so glass overlays them
      const glassSphere = new THREE.Mesh(glassGeo, glassMaterial);
      glassSphere.renderOrder = 2;
      nodeGroup.add(glassSphere);

      // 2) Logo/icon plane BEHIND the glass (MeshBasicMaterial = full color vibrancy)
      if (channels[i].logo) {
        const logoTex = loadLogoTexture(channels[i].logo!);
        const logoMat = new THREE.MeshBasicMaterial({
          map: logoTex,
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
        });
        const logoPlane = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), logoMat);
        logoPlane.renderOrder = 1;
        logoPlane.position.z = 0.1; // Slightly forward to avoid z-fighting
        nodeGroup.add(logoPlane);
      } else if (channels[i].icon) {
        const iconTex = createIconCanvas(channels[i].icon!, channels[i].color);
        const iconMat = new THREE.MeshBasicMaterial({
          map: iconTex,
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
        });
        const iconPlane = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), iconMat);
        iconPlane.renderOrder = 1;
        iconPlane.position.z = 0.1;
        nodeGroup.add(iconPlane);
      }

      // 3) Text label sprite below
      const textSprite = createTextSprite(channels[i].name);
      textSprite.position.y = -4.2;
      nodeGroup.add(textSprite);

      constellationGroup.add(nodeGroup);
      nodeGroups.push(nodeGroup);

      // 4) Tether line
      const tetherGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(x, y, z),
      ]);
      const tetherMat = new THREE.LineBasicMaterial({
        color: channels[i].color,
        transparent: true,
        opacity: 0.25,
        blending: THREE.AdditiveBlending,
      });
      const tether = new THREE.Line(tetherGeo, tetherMat);
      constellationGroup.add(tether);
    }

    // --- Animation Loop ---
    const clock = new THREE.Clock();
    function animate() {
      reqId = requestAnimationFrame(animate);
      const time = clock.getElapsedTime();

      // Gentle home float
      homeGroup.position.y = -1.5 + Math.sin(time * 1.5) * 0.4;

      // Rotate constellation smoothly
      constellationGroup.rotation.y += 0.0015;
      constellationGroup.rotation.x = Math.sin(time * 0.1) * 0.05;
      constellationGroup.rotation.z = Math.cos(time * 0.08) * 0.05;

      // Billboard each node group to face camera (logos always readable)
      for (const node of nodeGroups) {
        node.lookAt(camera.position);
      }

      controls.update();
      renderer.render(scene, camera);
    }

    animate();

    // --- Resize Handler ---
    let frameId: number;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (!mountRef.current) return;
        const width = mountRef.current.clientWidth;
        const height = mountRef.current.clientHeight;
        if (width === 0 || height === 0) return;
        
        renderer.setSize(width, height);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      }
    });
    resizeObserver.observe(mountRef.current);

    // --- Cleanup ---
    return () => {
      cancelAnimationFrame(reqId);
      resizeObserver.disconnect();
      if (mountRef.current && renderer.domElement) {
        // eslint-disable-next-line react-hooks/exhaustive-deps
        mountRef.current.removeChild(renderer.domElement);
      }
      renderer.dispose();
      scene.clear();
    };
  }, []); // Only run once on mount

  return (
    <div className="relative w-full h-[100dvh] min-h-[800px] bg-transparent">
      
      {/* Loading State / Error */}
      {(loading || errorMsg) && (
        <div className="absolute inset-0 flex flex-col justify-center items-center z-20 pointer-events-none">
          {errorMsg ? (
            <p className="text-red-400 font-semibold tracking-widest uppercase">{errorMsg}</p>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <div className="w-8 h-8 border-2 border-gold border-t-transparent rounded-full animate-spin" />
              <p className="text-gold font-semibold tracking-widest text-xs uppercase animate-pulse">Initializing Architecture...</p>
            </div>
          )}
        </div>
      )}

      {/* THREE.js Mount Node */}
      <div ref={mountRef} className="absolute inset-0 block cursor-grab active:cursor-grabbing" />
      
      {/* Absolute Header Overlay */}
      <div className="absolute top-8 left-8 md:top-12 md:left-12 z-20 pointer-events-none">
        <p className="text-gold text-[10px] md:text-xs font-semibold tracking-[0.2em] uppercase mb-2">Maximum Exposure</p>
        <h2 className="font-black text-white leading-tight tracking-tight mb-2 text-2xl md:text-4xl">
          Your Home,{' '}
          <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.4)' }}>
            Everywhere
          </span>
        </h2>
        <p className="text-white/50 text-xs md:text-sm font-light leading-relaxed max-w-sm hidden sm:block">
          Brandon broadcasts your property across 15+ premium channels simultaneously. Drag to explore the omnichannel constellation.
        </p>
      </div>
    </div>
  );
}
