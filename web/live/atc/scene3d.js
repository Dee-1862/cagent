import * as THREE from "three";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {mergeGeometries} from "three/addons/utils/BufferGeometryUtils.js";
import {RoomEnvironment} from "three/addons/environments/RoomEnvironment.js";

const colors = {blue:0x0a84ff, green:0x30d158, amber:0xffd60a, red:0xff453a, violet:0xbf5af2};
const models = ["small-plane", "helicopter", "jet", "airliner-747"];
const modelFor = (s, i) => {
  const name = `${s.name || ""} ${s.callsign || ""} ${s.spoken || ""} ${s.kind || ""}`.toLowerCase();
  return /helicopter|rotor/.test(name) ? models[1] : /cessna|small/.test(name) ? models[0] : /airliner|heavy|747/.test(name) ? models[3] : /jet/.test(name) ? models[2] : models[i % models.length];
};

export function createAirport(container, {quality = "high", followStation} = {}) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0b0d);
  scene.fog = new THREE.Fog(0x0a0b0d, 75, 170);
  const camera = new THREE.PerspectiveCamera(38, 1, .1, 320);
  camera.position.set(23, 30, 32);
  const renderer = new THREE.WebGLRenderer({antialias:quality!=="low", alpha:false});
  renderer.setPixelRatio(quality === "low" ? 1 : Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = quality === "high";
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.35;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  scene.environment = pmrem.fromScene(room).texture;
  room.dispose();
  const composer = null;  // bloom removed: it rendered only a corner of the frame; glow comes from emissive materials
  container.append(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enableDamping = true;
  controls.minDistance = 14; controls.maxDistance = 110;
  controls.maxPolarAngle = Math.PI / 2;
  controls.minPolarAngle = 0;
  const homeAngle = Math.atan2(23, 32);
  controls.minAzimuthAngle = -Infinity;
  controls.maxAzimuthAngle = Infinity;
  controls.autoRotate = false;
  controls.update();
  let idle = true, autoSway = true, viewName = "overview", transition = null;
  const views = {
    overview:{position:[44,46,62],target:[0,0,-3]},
    runway:{position:[8,15,44],target:[-10,0,16]},
    gates:{position:[20,28,14],target:[-4,0,-12]},
    top:{position:[0,100,-2.001],target:[0,0,-2]}
  };
  camera.position.set(...views.overview.position);controls.target.set(...views.overview.target);controls.update();
  function setView(name) {
    if(!views[name])return;
    viewName=name;idle=false;
    transition={start:performance.now(),from:camera.position.clone(),targetFrom:controls.target.clone(),to:new THREE.Vector3(...views[name].position),targetTo:new THREE.Vector3(...views[name].target)};
  }
  function setAutoSway(on){autoSway=!!on;idle=!!on;}
  renderer.domElement.addEventListener("pointerdown", () => { idle = false; });
  renderer.domElement.addEventListener("dblclick", () => setView("overview"));
  scene.add(new THREE.HemisphereLight(0xc5d4e4, 0x12151b, 2.1));
  const sun = new THREE.DirectionalLight(0xe9efff, 2.3);
  sun.position.set(-22, 40, 26); sun.castShadow = quality === "high";
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {left:-48,right:48,top:48,bottom:-48,near:1,far:120});
  sun.shadow.bias = -.0002; scene.add(sun);
  const materialCache = new Map();  // one material per colour+options, so batched markings share draw calls
  const matte = (c, extra = {}) => { const key = c + JSON.stringify(extra); if (!materialCache.has(key)) materialCache.set(key, new THREE.MeshStandardMaterial({color:c, roughness:1, metalness:0, ...extra})); return materialCache.get(key); };
  function box(w,h,d,x,y,z,material,shadow=false) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w,h,d), material);
    mesh.position.set(x,y,z); mesh.receiveShadow = true; mesh.castShadow = shadow; scene.add(mesh); return mesh;
  }
  // Flat markings and light dots are merged per material: one draw call each instead of hundreds.
  const batches=new Map();
  const addBatch=(geometry,material)=>{ if(!batches.has(material)) batches.set(material,[]); batches.get(material).push(geometry); };
  function mark(w,h,d,x,y,z,material){ const g=new THREE.BoxGeometry(w,h,d); g.translate(x,y,z); addBatch(g,material); }
  function dot(r,material,x,y,z){ const g=new THREE.SphereGeometry(r,6,4); g.translate(x,y,z); addBatch(g,material); }
  function flushBatches(){ for(const [material,list] of batches){ const merged=mergeGeometries(list,false); list.forEach(g=>g.dispose()); const m=new THREE.Mesh(merged,material); m.receiveShadow=true; scene.add(m);} batches.clear(); }
  // ---- ground: dark field, apron, fine grid (the digital-twin floor) ----
  box(260,.12,260,0,-.12,0,matte(0x0d0f12));
  mark(100,.02,40,0,-.04,-12,matte(0x14181d));
  const grid = new THREE.GridHelper(260, 260, 0x2d3842, 0x222b34);
  grid.material.transparent = true; grid.material.opacity = .14; grid.position.y = -.035; scene.add(grid);
  const majorGrid = new THREE.GridHelper(260, 26, 0x4a5763, 0x4a5763);
  majorGrid.material.transparent = true; majorGrid.material.opacity = .1; majorGrid.position.y = -.03; scene.add(majorGrid);

  // ---- runway 33/15 (south of the terminal) and taxiway B ----
  const RWY_Z = 22;
  box(76,.04,5.2,0,.005,RWY_Z,matte(0x1b2026));
  box(77,.015,6,0,-.005,RWY_Z,matte(0x2c343c));
  for (let x=-33; x<=33; x+=4.5) mark(1.8,.02,.13,x,.035,RWY_Z,matte(0xd4d9de));
  for (const dz of [-2.35,2.35]) mark(72,.02,.1,0,.035,RWY_Z+dz,matte(0xa6afb8));
  for (const x of [-35.5,35.5]) for (let k=-2;k<=2;k++) mark(.9,.02,.35,x,.035,RWY_Z+k*.85,matte(0xd4d9de));
  function paint(text,x,z,rotation=0) {
    const canvas=document.createElement("canvas"); canvas.width=256; canvas.height=256;
    const ctx=canvas.getContext("2d"); ctx.fillStyle="#e8ecef"; ctx.font="bold 165px Arial"; ctx.textAlign="center"; ctx.textBaseline="middle"; ctx.fillText(text,128,128);
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(3.4,3.4),new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(canvas),transparent:true,depthWrite:false}));
    mesh.rotation.x=-Math.PI/2; mesh.rotation.z=rotation; mesh.position.set(x,.055,z); scene.add(mesh);
  }
  paint("33",-32,RWY_Z,-Math.PI/2); paint("15",32,RWY_Z,Math.PI/2);
  const TWY_Z = 14;   // taxiway B, parallel to the runway
  mark(80,.035,2.6,-4,.012,TWY_Z,matte(0x20262c));
  for (let x=-43;x<35;x+=2.2) mark(1,.02,.07,x,.04,TWY_Z,matte(0xb7a478));
  mark(2.6,.035,RWY_Z-TWY_Z,-10,.012,(RWY_Z+TWY_Z)/2,matte(0x20262c));   // connector B1 onto the runway
  for (let z=TWY_Z+.8;z<RWY_Z-2.6;z+=1.4) mark(.07,.02,.8,-10,.04,z,matte(0xb7a478));
  const HOLD_Z = RWY_Z-3.4;   // hold-short line on the connector
  const hold=box(2.7,.025,.14,-10,.065,HOLD_Z,matte(colors.amber,{emissive:colors.amber,emissiveIntensity:.15}));
  mark(2.7,.025,.14,-10,.065,HOLD_Z-.3,matte(colors.amber));
  const twyLight=new THREE.MeshBasicMaterial({color:0x5fa8ff}), rwyLight=new THREE.MeshBasicMaterial({color:0xf2f4f6});
  for (let x=-43;x<35;x+=3.3) for (const dz of [-1.5,1.5]) { dot(.07,twyLight,x,.07,TWY_Z+dz); }
  for (let x=-36;x<=36;x+=2.4) for (const dz of [-2.9,2.9]) { dot(.06,rwyLight,x,.07,RWY_Z+dz); }

  // ---- terminal: a spine, three piers and a main hall; dark roof over a softly lit glass band ----
  const roofMat=new THREE.MeshStandardMaterial({color:0x22272e,metalness:.35,roughness:.45});
  const glassMat=new THREE.MeshStandardMaterial({color:0x2a3540,emissive:0x8fa6b8,emissiveIntensity:.12,metalness:.2,roughness:.3});
  const edgeMat=new THREE.LineBasicMaterial({color:0xc9d6e0,transparent:true,opacity:.45});
  const bridgeMat=new THREE.MeshStandardMaterial({color:0x9aa1a8,metalness:.25,roughness:.55});
  function slab(length,width,x,z,{angle=0,height=1.6,round=1}={}) {
    // A rounded slab: glass band below, a dark bevelled roof above with a light edge (as in the reference).
    const r=Math.min(width/2,round*width/2), l=length/2-r, w=width/2;
    const shape=new THREE.Shape();
    shape.moveTo(-l,-w); shape.lineTo(l,-w); shape.absarc(l,-w+r,r,-Math.PI/2,0,false); shape.lineTo(l+r,w-r);
    shape.absarc(l,w-r,r,0,Math.PI/2,false); shape.lineTo(-l,w); shape.absarc(-l,w-r,r,Math.PI/2,Math.PI,false);
    shape.lineTo(-l-r,-w+r); shape.absarc(-l,-w+r,r,Math.PI,1.5*Math.PI,false);
    const roof=new THREE.ExtrudeGeometry(shape,{depth:.35,bevelEnabled:true,bevelThickness:.25,bevelSize:.3,bevelSegments:5,curveSegments:16});
    roof.rotateX(-Math.PI/2);
    const g=new THREE.Group(); g.position.set(x,0,z); g.rotation.y=angle; scene.add(g);
    const roofMesh=new THREE.Mesh(roof,roofMat); roofMesh.position.y=height; roofMesh.castShadow=quality==="high"; roofMesh.receiveShadow=true; g.add(roofMesh);
    const edge=new THREE.LineSegments(new THREE.EdgesGeometry(roof,30),edgeMat); edge.position.y=height; g.add(edge);
    const bandGeo=new THREE.ExtrudeGeometry(shape,{depth:height,bevelEnabled:false,curveSegments:16}); bandGeo.rotateX(-Math.PI/2); bandGeo.scale(.94,1,.9);
    g.add(new THREE.Mesh(bandGeo,glassMat));
    return g;
  }
  const SPINE_Z=-26;
  slab(66,3.6,-4,SPINE_Z,{height:1.5});                                   // spine
  const PIERS=[-28,-5,18];
  for (const px of PIERS) slab(26,2.8,px,SPINE_Z+14.2,{angle:Math.PI/2,height:1.35});   // piers point south, toward the airfield
  slab(13,11,36,SPINE_Z+2.5,{height:2.2,round:.55});                      // main hall
  const sky=new THREE.Mesh(new THREE.CircleGeometry(2.2,32),new THREE.MeshBasicMaterial({color:0x5b8fb8,transparent:true,opacity:.55}));
  sky.rotation.x=-Math.PI/2; sky.scale.set(1.6,1,1); sky.position.set(36,2.95,SPINE_Z+2.5); scene.add(sky);

  // ---- jet bridges along both sides of each pier; white airliners parked nose-in ----
  const gateSpots=[];
  for (const px of PIERS) for (const side of [-1,1]) for (let i=0;i<4;i++) {
    const z=SPINE_Z+6+i*6.2, x0=px+side*1.7;
    box(2.6,.55,.6,x0+side*1.3,1.05,z,bridgeMat,true);
    const rot=new THREE.Mesh(new THREE.CylinderGeometry(.42,.42,.62,12),bridgeMat); rot.position.set(x0+side*2.75,1.05,z); rot.castShadow=quality==="high"; scene.add(rot);
    for (const lx of [x0+side*1.6,x0+side*2.75]) box(.08,.8,.08,lx,.4,z,bridgeMat);
    gateSpots.push({x:x0+side*6.0,z,noseYaw:side>0?Math.PI:0});           // nose points back at the pier
  }
  const tmpV=new THREE.Vector3();
  function prepareAircraft(root,length) {
    // A group whose +X is the aircraft's nose (the tail fin is the model's highest point), scaled to `length`.
    root.updateMatrixWorld(true);
    root.traverse(o=>{ if(o.isMesh && o.geometry && !o.geometry.attributes.normal) o.geometry.computeVertexNormals(); });
    const box0=new THREE.Box3().setFromObject(root), size0=box0.getSize(new THREE.Vector3());
    const longX=size0.x>=size0.z; let top=-Infinity, along=0;
    root.traverse(o=>{ if(!o.isMesh) return; const pos=o.geometry.attributes.position; const step=Math.max(1,Math.floor(pos.count/3000));
      for(let i=0;i<pos.count;i+=step){ tmpV.fromBufferAttribute(pos,i).applyMatrix4(o.matrixWorld); if(tmpV.y>top){top=tmpV.y; along=longX?tmpV.x:tmpV.z;} } });
    const mid=longX?(box0.min.x+box0.max.x)/2:(box0.min.z+box0.max.z)/2, tailPositive=along>mid;
    const turn=new THREE.Group(); turn.add(root);
    turn.rotation.y = longX ? (tailPositive?Math.PI:0) : (tailPositive?-Math.PI/2:Math.PI/2);
    const holder=new THREE.Group(); holder.add(turn); holder.updateMatrixWorld(true);
    const size1=new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3());
    holder.scale.setScalar(length/Math.max(size1.x,size1.z)); holder.updateMatrixWorld(true);
    const box2=new THREE.Box3().setFromObject(holder), c=box2.getCenter(new THREE.Vector3());
    turn.position.set(-c.x/holder.scale.x,-box2.min.y/holder.scale.y,-c.z/holder.scale.z);
    root.traverse(o=>{ if(o.isMesh){ o.material=new THREE.MeshStandardMaterial({color:0xe9ecef,roughness:.5,metalness:.05,side:THREE.DoubleSide}); o.castShadow=quality==="high"; o.receiveShadow=true; } });
    return holder;
  }
  const parkedTypes=["airliner-a","airliner-b","regional-jet","airliner-747","airliner-a","airliner-b"];
  // "low" (narrow screens, the headless recorder) skips the parked fleet: it's decoration and the heaviest part.
  if (quality!=="low") gateSpots.filter((_,i)=>i%4!==3).forEach(async (spot,i)=>{ try {
    const gltf=await new GLTFLoader().loadAsync(`/live/static/atc/models/${parkedTypes[i%parkedTypes.length]}.glb`); if(disposed) return;
    const plane=prepareAircraft(gltf.scene,5.6); plane.position.set(spot.x,0,spot.z); plane.rotation.y=spot.noseYaw; scene.add(plane);
  } catch(e) { console.warn("Parked aircraft unavailable",e); } });

  // ---- taxi routes: every gate -> lead-in line -> taxiway A (pier tips) -> connector -> taxiway B -> hold short -> runway ----
  const TWYA_Z = SPINE_Z+30.5;
  const taxiMat=matte(0x20262c), lineMat=matte(0xb7a478,{emissive:0xb7a478,emissiveIntensity:.08});
  mark(84,.035,2.4,0,.012,TWYA_Z,taxiMat);
  for (let x=-41;x<42;x+=2.2) mark(1,.02,.07,x,.04,TWYA_Z,lineMat);
  for (const cx of [-38,-17,6,30]) {
    mark(2.4,.035,TWY_Z-TWYA_Z,cx,.012,(TWY_Z+TWYA_Z)/2,taxiMat);
    for (let z=TWYA_Z+.9;z<TWY_Z-.9;z+=1.3) mark(.07,.02,.75,cx,.04,z,lineMat);
  }
  for (const spot of gateSpots) {                                     // lead-in: from the stand out to taxiway A
    const len=TWYA_Z-spot.z; mark(.08,.02,len,spot.x,.04,spot.z+len/2,lineMat);
    mark(.9,.02,.08,spot.x,.04,spot.z,lineMat);                        // stop bar at the stand
  }
  // ---- control tower, west of the field ----
  const TOWER={x:-46,z:-8};
  const shaft=new THREE.Mesh(new THREE.CylinderGeometry(.45,.7,9,20),roofMat); shaft.position.set(TOWER.x,4.5,TOWER.z); shaft.castShadow=quality==="high"; scene.add(shaft);
  const towerCab=new THREE.Mesh(new THREE.CylinderGeometry(1.35,1.05,1.1,16),glassMat); towerCab.position.set(TOWER.x,9.4,TOWER.z); scene.add(towerCab);
  const cab=new THREE.Mesh(new THREE.CylinderGeometry(1.55,1.55,.18,16),roofMat); cab.position.set(TOWER.x,10.05,TOWER.z); scene.add(cab);

  // ---- apron lights: small scattered points, like the reference ----
  const lightMat=new THREE.MeshBasicMaterial({color:0xdfe7ee});
  for(let i=0;i<(quality==="low"?30:90);i++) {
    const x=-44+((i*37)%92), z=-30+((i*53)%36);
    dot(.06,lightMat,x,.05,z);
  }
  flushBatches();
  const loader=new GLTFLoader();
  const entries=new Map(); let selected=null, disposed=false, onPick=()=>{};
  const raycaster=new THREE.Raycaster(); const pointer=new THREE.Vector2();
  // Taxi model: planes queue nose-east on taxiway B toward connector B1, then hold short, line up and
  // depart on runway 33. Each new plane joins the back of the queue; the queue moves up when one leaves.
  const CONN_X=-10, HOLD_STOP_Z=HOLD_Z-1.4, QUEUE_X0=-16, QUEUE_GAP=6.5, TAXI=3.2;
  const queueSpot=i=>new THREE.Vector3(QUEUE_X0-i*QUEUE_GAP,0,TWY_Z);
  let queueSerial=0;
  const queued=()=>[...entries.values()].filter(e=>e.state==="queue"&&!e.removing).sort((a,b)=>a.queueOrder-b.queueOrder);
  function reflow(){
    queued().forEach((e,i)=>{ const spot=queueSpot(i); const last=e.path.at(-1);
      if(e.group.position.distanceTo(spot)>.05 && !(last && last.distanceTo(spot)<.05)) { e.path=[spot]; e.speed=TAXI; } });
  }
  const toHold=()=>[new THREE.Vector3(CONN_X,0,TWY_Z),new THREE.Vector3(CONN_X,0,HOLD_STOP_Z)];
  const toLineUp=()=>[new THREE.Vector3(CONN_X,0,RWY_Z),new THREE.Vector3(CONN_X+3,0,RWY_Z)];
  function command(id,action){
    // A heard instruction moves the plane. Returns false when it doesn't apply in the plane's current state.
    const e=entries.get(id); if(!e||e.removing) return false;
    const airborne=["takeoff","departed"].includes(e.state);
    const leaveQueue=()=>{ if(e.state==="queue"){ e.state="taxi"; reflow(); } };
    if(action==="stop"){ if(airborne) return false; e.path=[]; e.after=null; if(e.state!=="queue") e.state="stopped"; return true; }
    if(action==="hold_short"){ if(airborne||["holding","lined_up"].includes(e.state)) return false;
      leaveQueue(); e.path=toHold(); e.after="holding"; e.speed=TAXI; return true; }
    if(action==="line_up"){ if(airborne||e.state==="lined_up") return false;
      leaveQueue(); e.path=[...(e.state==="holding"?[]:toHold()),...toLineUp()]; e.after="lined_up"; e.speed=TAXI; return true; }
    if(action==="takeoff"){ if(airborne) return false;
      leaveQueue(); e.path=e.state==="lined_up"?[]:[...(e.state==="holding"?[]:toHold()),...toLineUp()]; e.after="takeoff"; e.speed=TAXI;
      if(!e.path.length){ e.state="takeoff"; e.after=null; e.v=2; } return true; }
    return false;
  }
  const turn=(from,to)=>{ let d=to-from; while(d>Math.PI) d-=2*Math.PI; while(d<-Math.PI) d+=2*Math.PI; return d; };
  const ringGeometry=new THREE.RingGeometry(2.3,2.5,64);
  const towerRing=new THREE.Mesh(ringGeometry,new THREE.MeshBasicMaterial({color:colors.blue,transparent:true,opacity:0,side:THREE.DoubleSide,depthWrite:false}));
  towerRing.rotation.x=-Math.PI/2;towerRing.position.set(TOWER.x,.09,TOWER.z);scene.add(towerRing);
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
      entry.group.add(prepareAircraft(gltf.scene,/helicopter/.test(type)?3.6:4.6));
    } catch(error) {console.warn("Aircraft model unavailable",type,error);}
  }
  function setStations(list) {
    const aircraft=list.filter(s=>s.kind==="aircraft" || /helicopter|rotor/i.test(s.kind || ""));
    const present=new Set(aircraft.map(s=>s.id));
    for(const [id,e] of entries) if(!present.has(id)) e.removing=true;
    aircraft.forEach((s,i)=>{
      if(entries.has(s.id)) {entries.get(s.id).station=s;entries.get(s.id).removing=false;return;}
      const {x,z}=queueSpot(queued().length);                         // join the back of the queue
      const group=new THREE.Group(); group.position.set(x,0,z); group.rotation.y=0; scene.add(group);
      const e={id:s.id,station:s,group,ring:ring(colors.blue),born:performance.now(),removing:false,opacity:1,flashUntil:0,needs:false,hold:false,
               state:"queue",queueOrder:queueSerial++,path:[],after:null,speed:TAXI,yaw:0,targetYaw:0,alt:0,pitch:0,fade:1,v:0};
      e.ring.position.set(x,.07,z); entries.set(s.id,e); attachModel(e,modelFor(s,i));
    });
    reflow();
  }
  let keyedIds=new Set(), steppedIds=new Set();
  function keyed(ids) {keyedIds=new Set(Array.isArray(ids)?ids:Object.keys(ids||{}));}
  function steppedOn(ids) {steppedIds=new Set(ids); ids.forEach(id=>{const e=entries.get(id);if(e) flash(e,colors.red,2500);}); setTimeout(()=>{steppedIds.clear();},2500);}
  function advisory(id) {const e=entries.get(id);if(e){
    flash(e,colors.violet,2400);
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(TOWER.x,9.4,TOWER.z),e.group.position.clone().add(new THREE.Vector3(0,1.1,0))]),beamMaterial.clone());
    scene.add(line);beams.push({line,until:performance.now()+2400});
  }}
  function readback(id,ok) {const e=entries.get(id);if(e) flash(e,ok?colors.green:colors.red);}
  function holdShort(id,on) {const e=entries.get(id);if(e)e.hold=on;}
  function needsYou(id,on) {const e=entries.get(id);if(e)e.needs=on;}
  function project(id) {
    const e=entries.get(id); if(!e)return null;
    const p=e.group.position.clone().add(new THREE.Vector3(0,3,0)).project(camera);
    return {x:(p.x+1)*container.clientWidth/2,y:(1-p.y)*container.clientHeight/2,visible:p.z<1 && p.z>-1,opacity:e.opacity};
  }
  function click(event) {
    const rect=renderer.domElement.getBoundingClientRect(); pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hits=raycaster.intersectObjects([...entries.values()].map(e=>e.group),true);
    if(hits.length){let o=hits[0].object;while(o.parent && ![...entries.values()].some(e=>e.group===o))o=o.parent;const e=[...entries.values()].find(e=>e.group===o);if(e){selected=e.id;onPick(e.id);}}
  }
  renderer.domElement.addEventListener("click",click);
  const size=()=>{
    const w=container.clientWidth,h=container.clientHeight;
    if(!w||!h)return;
    const column=Math.min(360,Math.max(0,w-700));
    camera.aspect=w/h;
    camera.setViewOffset(w+column,h,column,0,w,h);
    camera.updateProjectionMatrix();renderer.setSize(w,h);composer?.setSize(w,h);
  };
  const observer=new ResizeObserver(size);observer.observe(container);size();
  const clock=new THREE.Clock();let frame=0;
  function animate() {
    if(disposed)return; frame=requestAnimationFrame(animate);
    if(document.hidden)return;
    const t=performance.now(), dt=clock.getDelta();
    if(transition){
      const p=Math.min(1,(t-transition.start)/800),ease=p*p*(3-2*p);
      camera.position.copy(transition.from).lerp(transition.to,ease);
      controls.target.copy(transition.targetFrom).lerp(transition.targetTo,ease);
      if(p===1)transition=null;
    } else if (idle && autoSway && viewName==="overview" && !reduced.matches && !followStation) {
      camera.position.x=views.overview.position[0]+Math.sin(t/9000)*1.5;
    }
    controls.update();
    hold.material.emissiveIntensity=[...entries.values()].some(e=>e.hold||e.state==="holding") ? (reduced.matches?.8:.65+.25*Math.sin(t/260)) : .15;
    towerRing.visible=keyedIds.has("atc");
    if(towerRing.visible){towerRing.scale.setScalar(reduced.matches?1.1:1+(t%1300)/1300*2);towerRing.material.opacity=reduced.matches?.75:1-(t%1300)/1300;}
    for(let i=beams.length-1;i>=0;i--){const b=beams[i];b.line.material.opacity=Math.max(0,(b.until-t)/2400)*.8;if(t>=b.until){scene.remove(b.line);b.line.geometry.dispose();b.line.material.dispose();beams.splice(i,1);}}
    for(const [id,e] of entries) {
      const age=(t-e.born)/600, spawn=reduced.matches?1:Math.min(1,Math.max(0,1-Math.pow(1-age,3)));
      e.opacity=e.removing?Math.max(0,e.opacity-dt*1.5):spawn;
      // taxi along the path, turning smoothly toward the next point
      if(e.path.length){
        const target=e.path[0], p=e.group.position, dx=target.x-p.x, dz=target.z-p.z, d=Math.hypot(dx,dz), step=e.speed*dt;
        if(d<=step){ p.x=target.x; p.z=target.z; e.path.shift();
          if(!e.path.length&&e.after){ e.state=e.after; e.after=null; if(e.state==="takeoff") e.v=2; } }
        else { p.x+=dx/d*step; p.z+=dz/d*step; e.targetYaw=Math.atan2(-dz,dx); }
      }
      if(e.state==="takeoff"){                                         // roll, rotate, climb out
        e.v=Math.min(28,e.v+7*dt); e.group.position.x+=e.v*dt; e.targetYaw=0;
        if(e.group.position.x>CONN_X+16){ e.alt+=e.v*.24*dt; e.pitch=Math.min(.2,e.pitch+dt*.35); }
        if(e.group.position.x>60||e.alt>16){ e.state="departed"; e.departedAt=t; }
      }
      if(e.state==="departed"){
        e.fade=Math.max(0,e.fade-dt*1.4);
        if(t-e.departedAt>3500){                                       // the circuit ends: rejoin the back of the queue
          const spot=queueSpot(queued().length); e.state="queue"; e.queueOrder=queueSerial++; e.alt=0; e.pitch=0; e.fade=1; e.v=0;
          e.group.position.set(spot.x,0,spot.z); e.yaw=e.targetYaw=0; e.born=t; reflow();
        }
      }
      e.yaw+=turn(e.yaw,e.targetYaw)*Math.min(1,dt*5); e.group.rotation.set(0,e.yaw,e.pitch);
      e.group.position.y=(e.removing?(1-e.opacity)*2:(1-spawn)*2)+(e.needs&&!reduced.matches?.12*Math.sin(t/320):0)+e.alt;
      e.group.scale.setScalar(Math.max(.001,e.opacity*e.fade));
      e.ring.position.set(e.group.position.x,.07,e.group.position.z);
      e.ring.visible=e.alt<.5&&(keyedIds.has(id)||steppedIds.has(id)||t<e.flashUntil||age<1.3||e.needs);
      const color=steppedIds.has(id)?colors.red:t<e.flashUntil?e.flashColor:e.needs?colors.amber:colors.blue;
      e.ring.material.color.setHex(color);
      const pulse=keyedIds.has(id)&&!reduced.matches?1+(t%1300)/1300*2:1.15;
      e.ring.scale.setScalar(pulse);
      e.ring.material.opacity=e.opacity*(reduced.matches?.75:keyedIds.has(id)?1-(t%1300)/1300:.7);
      if(e.removing&&e.opacity===0){scene.remove(e.group,e.ring);e.ring.material.dispose();entries.delete(id);reflow();}
    }
    if(composer)composer.render();else renderer.render(scene,camera);
  }
  animate();
  return {setStations,command,keyed,steppedOn,advisory,readback,holdShort,needsYou,setView,setAutoSway,onSelect(callback){onPick=callback;},project,dispose(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();renderer.domElement.removeEventListener("click",click);for(const b of beams){b.line.geometry.dispose();b.line.material.dispose();}ringGeometry.dispose();towerRing.material.dispose();composer?.dispose();pmrem.dispose();renderer.dispose();container.replaceChildren();}};
}
