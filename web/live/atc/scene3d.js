import * as THREE from "three";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";

const colors = {blue:0x0a84ff, green:0x30d158, amber:0xffd60a, red:0xff453a, violet:0xbf5af2};
const models = ["small-plane", "helicopter", "jet", "airliner-747"];
const modelFor = (s, i) => {
  const name = `${s.name || ""} ${s.callsign || ""} ${s.spoken || ""} ${s.kind || ""}`.toLowerCase();
  return /helicopter|rotor/.test(name) ? models[1] : /cessna|small/.test(name) ? models[0] : /airliner|heavy|747/.test(name) ? models[3] : /jet/.test(name) ? models[2] : models[i % models.length];
};

export function createAirport(container, {quality = "high", followStation} = {}) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d10);
  scene.fog = new THREE.Fog(0x0b0d10, 42, 95);
  const camera = new THREE.PerspectiveCamera(40, 1, .1, 160);
  camera.position.set(23, 24, 27);
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = quality === "high";
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.append(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enableDamping = true;
  controls.minDistance = 17; controls.maxDistance = 65;
  controls.maxPolarAngle = Math.PI * .46;
  controls.minPolarAngle = Math.PI * .16;
  controls.autoRotate = !reduced.matches;
  controls.autoRotateSpeed = .25;
  controls.update();
  renderer.domElement.addEventListener("dblclick", () => {camera.position.set(23,24,27); controls.target.set(0,0,0); controls.update();});
  scene.add(new THREE.HemisphereLight(0xb9d8ff, 0x20232a, 2.2));
  const sun = new THREE.DirectionalLight(0xffe9d0, 2.5);
  sun.position.set(-12, 25, 14); sun.castShadow = quality === "high";
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {left:-28,right:28,top:28,bottom:-28,near:1,far:65});
  sun.shadow.bias = -.0002; scene.add(sun);
  const matte = (c, extra = {}) => new THREE.MeshStandardMaterial({color:c, roughness:1, metalness:0, ...extra});
  function box(w,h,d,x,y,z,material,shadow=false) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w,h,d), material);
    mesh.position.set(x,y,z); mesh.receiveShadow = true; mesh.castShadow = shadow; scene.add(mesh); return mesh;
  }
  box(100,.12,100,0,-.12,0,matte(0x14181d));
  box(6,.04,42,0,.005,0,matte(0x252b32));
  box(6.8,.015,43,0,-.005,0,matte(0x323a43));
  for (let z=-17; z<=17; z+=4) box(.12,.02,1.6,0,.035,z,matte(0xd4d9de));
  for (const x of [-2.65,2.65]) box(.1,.02,39,x,.035,0,matte(0xa6afb8));
  function paint(text,z,rotation=0) {
    const canvas=document.createElement("canvas"); canvas.width=256; canvas.height=256;
    const ctx=canvas.getContext("2d"); ctx.fillStyle="#e8ecef"; ctx.font="bold 165px Arial"; ctx.textAlign="center"; ctx.textBaseline="middle"; ctx.fillText(text,128,128);
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(3,3),new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(canvas),transparent:true,depthWrite:false}));
    mesh.rotation.x=-Math.PI/2; mesh.rotation.z=rotation; mesh.position.set(0,.055,z); scene.add(mesh);
  }
  paint("33",-18); paint("15",18,Math.PI);
  box(19,.035,4.5,-11,.015,0,matte(0x313940));
  for (let x=-20;x<-3;x+=3) box(1.1,.02,.09,x,.045,0,matte(0xb7a478));
  const hold=box(.14,.025,4.7,-3.55,.065,0,matte(colors.amber,{emissive:colors.amber,emissiveIntensity:.15}));
  box(.14,.025,4.7,-3.85,.065,0,matte(colors.amber));
  for(let i=0;i<7;i++) {
    const x=-20+i*2.35;
    box(.08,.018,3,x,.045,-7.4,matte(0x57616a));
    box(.08,.018,3,x,.045,7.4,matte(0x57616a));
  }
  box(2.2,6,2.2,8,3,-8,matte(0x343c46),true);
  box(3.1,1.5,3.1,8,6.75,-8,matte(0x183656,{emissive:colors.blue,emissiveIntensity:.35}),true);
  const cab=new THREE.Mesh(new THREE.CylinderGeometry(1.75,1.75,.22,8),matte(0x394451)); cab.position.set(8,7.65,-8); cab.castShadow=true; scene.add(cab);
  box(2,.02,1,8,.02,-4.7,matte(0x52708b));
  const loader=new GLTFLoader();
  const entries=new Map(); let selected=null, disposed=false, onPick=()=>{};
  const raycaster=new THREE.Raycaster(); const pointer=new THREE.Vector2();
  const slots=[[-17,0],[-11,0],[-18,-7.4],[-12,-7.4],[-18,7.4],[-12,7.4],[-6,-7.4],[-6,7.4]];
  const ringGeometry=new THREE.RingGeometry(.95,1.06,48);
  const towerRing=new THREE.Mesh(ringGeometry,new THREE.MeshBasicMaterial({color:colors.blue,transparent:true,opacity:0,side:THREE.DoubleSide,depthWrite:false}));
  towerRing.rotation.x=-Math.PI/2;towerRing.position.set(8,.09,-8);scene.add(towerRing);
  const beamMaterial=new THREE.LineBasicMaterial({color:colors.violet,transparent:true,opacity:.8});
  const beams=[];
  function ring(color) {
    const mesh=new THREE.Mesh(ringGeometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.8,side:THREE.DoubleSide,depthWrite:false}));
    mesh.rotation.x=-Math.PI/2; mesh.position.y=.08; scene.add(mesh); return mesh;
  }
  function flash(entry,color,duration=3000) {entry.flashColor=color;entry.flashUntil=performance.now()+duration;}
  async function attachModel(entry,type) {
    try {
      const gltf=await loader.loadAsync(`/live/static/atc/models/${type}.glb`);
      if(disposed || entries.get(entry.id)!==entry) return;
      const root=gltf.scene;
      const bounds=new THREE.Box3().setFromObject(root), size=bounds.getSize(new THREE.Vector3());
      root.scale.setScalar(2.5/Math.max(size.x,size.z,size.y));
      const fitted=new THREE.Box3().setFromObject(root), center=fitted.getCenter(new THREE.Vector3());
      root.position.set(-center.x,-fitted.min.y,-center.z);
      root.traverse(o=>{if(o.isMesh){o.castShadow=quality==="high";o.receiveShadow=true;}});
      entry.group.add(root);
    } catch(error) {console.warn("Aircraft model unavailable",type,error);}
  }
  function setStations(list) {
    const aircraft=list.filter(s=>s.kind==="aircraft" || /helicopter|rotor/i.test(s.kind || ""));
    const present=new Set(aircraft.map(s=>s.id));
    for(const [id,e] of entries) if(!present.has(id)) e.removing=true;
    aircraft.forEach((s,i)=>{
      if(entries.has(s.id)) {entries.get(s.id).station=s;entries.get(s.id).removing=false;return;}
      const [x,z]=slots[i%slots.length];
      const group=new THREE.Group(); group.position.set(x,0,z); group.rotation.y=Math.PI/2; scene.add(group);
      const e={id:s.id,station:s,group,ring:ring(colors.blue),born:performance.now(),removing:false,opacity:1,flashUntil:0,needs:false,hold:false};
      e.ring.position.set(x,.07,z); entries.set(s.id,e); attachModel(e,modelFor(s,i));
    });
  }
  let keyedIds=new Set(), steppedIds=new Set();
  function keyed(ids) {keyedIds=new Set(Array.isArray(ids)?ids:Object.keys(ids||{}));}
  function steppedOn(ids) {steppedIds=new Set(ids); ids.forEach(id=>{const e=entries.get(id);if(e) flash(e,colors.red,2500);}); setTimeout(()=>{steppedIds.clear();},2500);}
  function advisory(id) {const e=entries.get(id);if(e){
    flash(e,colors.violet,2400);
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(8,6.8,-8),e.group.position.clone().add(new THREE.Vector3(0,1.1,0))]),beamMaterial.clone());
    scene.add(line);beams.push({line,until:performance.now()+2400});
  }}
  function readback(id,ok) {const e=entries.get(id);if(e) flash(e,ok?colors.green:colors.red);}
  function holdShort(id,on) {const e=entries.get(id);if(e)e.hold=on;}
  function needsYou(id,on) {const e=entries.get(id);if(e)e.needs=on;}
  function project(id) {
    const e=entries.get(id); if(!e)return null;
    const p=e.group.position.clone().add(new THREE.Vector3(0,2.2,0)).project(camera);
    return {x:(p.x+1)*container.clientWidth/2,y:(1-p.y)*container.clientHeight/2,visible:p.z<1 && p.z>-1,opacity:e.opacity};
  }
  function click(event) {
    const rect=renderer.domElement.getBoundingClientRect(); pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hits=raycaster.intersectObjects([...entries.values()].map(e=>e.group),true);
    if(hits.length){let o=hits[0].object;while(o.parent && ![...entries.values()].some(e=>e.group===o))o=o.parent;const e=[...entries.values()].find(e=>e.group===o);if(e){selected=e.id;onPick(e.id);}}
  }
  renderer.domElement.addEventListener("click",click);
  const size=()=>{if(!container.clientWidth||!container.clientHeight)return;camera.aspect=container.clientWidth/container.clientHeight;camera.updateProjectionMatrix();renderer.setSize(container.clientWidth,container.clientHeight);};
  const observer=new ResizeObserver(size);observer.observe(container);size();
  const clock=new THREE.Clock();let frame=0;
  function animate() {
    if(disposed)return; frame=requestAnimationFrame(animate);
    if(document.hidden)return;
    const t=performance.now(), dt=clock.getDelta();
    controls.autoRotate=!reduced.matches && !followStation; controls.update();
    hold.material.emissiveIntensity=[...entries.values()].some(e=>e.hold) ? (reduced.matches?.8:.65+.25*Math.sin(t/260)) : .15;
    towerRing.visible=keyedIds.has("atc");
    if(towerRing.visible){towerRing.scale.setScalar(reduced.matches?1.1:1+(t%1300)/1300*2);towerRing.material.opacity=reduced.matches?.75:1-(t%1300)/1300;}
    for(let i=beams.length-1;i>=0;i--){const b=beams[i];b.line.material.opacity=Math.max(0,(b.until-t)/2400)*.8;if(t>=b.until){scene.remove(b.line);b.line.geometry.dispose();b.line.material.dispose();beams.splice(i,1);}}
    for(const [id,e] of entries) {
      const age=(t-e.born)/600, spawn=reduced.matches?1:Math.min(1,Math.max(0,1-Math.pow(1-age,3)));
      e.opacity=e.removing?Math.max(0,e.opacity-dt*1.5):spawn;
      e.group.position.y=(e.removing?(1-e.opacity)*2:(1-spawn)*2)+(e.needs&&!reduced.matches?.12*Math.sin(t/320):0);
      e.group.scale.setScalar(Math.max(.001,e.opacity));
      e.ring.visible=keyedIds.has(id)||steppedIds.has(id)||t<e.flashUntil||age<1.3||e.needs;
      const color=steppedIds.has(id)?colors.red:t<e.flashUntil?e.flashColor:e.needs?colors.amber:colors.blue;
      e.ring.material.color.setHex(color);
      const pulse=keyedIds.has(id)&&!reduced.matches?1+(t%1300)/1300*2:1.15;
      e.ring.scale.setScalar(pulse);
      e.ring.material.opacity=e.opacity*(reduced.matches?.75:keyedIds.has(id)?1-(t%1300)/1300:.7);
      if(e.removing&&e.opacity===0){scene.remove(e.group,e.ring);e.ring.material.dispose();entries.delete(id);}
    }
    renderer.render(scene,camera);
  }
  animate();
  return {setStations,keyed,steppedOn,advisory,readback,holdShort,needsYou,onSelect(callback){onPick=callback;},project,dispose(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();renderer.domElement.removeEventListener("click",click);for(const b of beams){b.line.geometry.dispose();b.line.material.dispose();}ringGeometry.dispose();towerRing.material.dispose();renderer.dispose();container.replaceChildren();}};
}
