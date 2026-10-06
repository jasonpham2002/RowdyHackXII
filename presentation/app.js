/* Prezi-style camera. Clicking a title zooms the map into that frame. */

const ORDER = ["job", "pipe", "lang", "show", "after"];
const LABELS = {
  job: "01 · The job",
  pipe: "02 · The pipeline",
  lang: "03 · Blink language",
  show: "04 · What you will show",
  after: "05 · Limits and next"
};
const WORLD = { w: 2200, h: 1500 };

const state = {
  focus: null
};

const world = document.getElementById("world");
const stamp = document.getElementById("stamp");

function frameBox(id) {
  const frame = document.querySelector(`.frame[data-id="${id}"]`);
  return {
    x: frame.offsetLeft,
    y: frame.offsetTop,
    w: frame.offsetWidth,
    h: frame.offsetHeight
  };
}

function overviewCamera() {
  const scale = Math.min(window.innerWidth / WORLD.w, window.innerHeight / WORLD.h) * 0.92;
  return {
    scale,
    x: (window.innerWidth - WORLD.w * scale) / 2,
    y: (window.innerHeight - WORLD.h * scale) / 2
  };
}

function frameCamera(id) {
  const box = frameBox(id);
  const scale = Math.min((window.innerWidth * 0.78) / box.w, (window.innerHeight * 0.72) / box.h);
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  return {
    scale,
    x: window.innerWidth / 2 - cx * scale,
    y: window.innerHeight / 2 - cy * scale
  };
}

function applyCamera(camera) {
  world.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
}

function render() {
  document.querySelectorAll(".frame").forEach((frame) => {
    const on = frame.dataset.id === state.focus;
    frame.classList.toggle("is-focus", on);
    if (on) frame.setAttribute("aria-current", "true");
    else frame.removeAttribute("aria-current");
  });
  stamp.textContent = state.focus ? LABELS[state.focus] : "Map";
}

function zoomTo(id) {
  state.focus = id;
  applyCamera(frameCamera(id));
  render();
}

function showOverview() {
  state.focus = null;
  applyCamera(overviewCamera());
  render();
}

function step(delta) {
  const index = state.focus ? ORDER.indexOf(state.focus) : -1;
  const next = (index + delta + ORDER.length) % ORDER.length;
  zoomTo(ORDER[next]);
}

// #region agent log
fetch("http://127.0.0.1:7586/ingest/b2849dbb-da5c-4726-8ab3-1a8477f4c79f",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"fb993d"},body:JSON.stringify({sessionId:"fb993d",hypothesisId:"A",location:"presentation/app.js:boot",message:"presentation boot",data:{world:!!document.getElementById("world"),overview:!!document.getElementById("overview"),frames:document.querySelectorAll(".frame").length,zones:document.querySelectorAll(".zone").length,playSos:!!document.getElementById("play-sos"),room:!!document.getElementById("room")},timestamp:Date.now()})}).catch(()=>{});
document.addEventListener("click",(event)=>{const t=event.target;fetch("http://127.0.0.1:7586/ingest/b2849dbb-da5c-4726-8ab3-1a8477f4c79f",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"fb993d"},body:JSON.stringify({sessionId:"fb993d",hypothesisId:"B",location:"presentation/app.js:click",message:"click",data:{tag:t&&t.tagName,id:t&&t.id,className:String(t&&t.className),pointerEvents:t?getComputedStyle(t).pointerEvents:""},timestamp:Date.now()})}).catch(()=>{});},true);
// #endregion
document.querySelectorAll(".frame").forEach((frame) => {
  frame.addEventListener("click", (event) => {
    event.stopPropagation();
    if (state.focus === frame.dataset.id) showOverview();
    else zoomTo(frame.dataset.id);
  });
});

try {
  document.getElementById("overview").addEventListener("click", showOverview);
} catch (err) {
  // #region agent log
  fetch("http://127.0.0.1:7586/ingest/b2849dbb-da5c-4726-8ab3-1a8477f4c79f",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"fb993d"},body:JSON.stringify({sessionId:"fb993d",hypothesisId:"A",location:"presentation/app.js:overview",message:"overview bind failed",data:{error:String(err)},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
}

window.addEventListener("keydown", (event) => {
  const index = ["1", "2", "3", "4", "5"].indexOf(event.key);
  if (index >= 0) {
    event.preventDefault();
    zoomTo(ORDER[index]);
    return;
  }
  if (event.key === "Escape" || event.key === "0") {
    event.preventDefault();
    showOverview();
    return;
  }
  if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    event.preventDefault();
    step(1);
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    event.preventDefault();
    step(-1);
  }
});

window.addEventListener("resize", () => {
  applyCamera(state.focus ? frameCamera(state.focus) : overviewCamera());
});

applyCamera(overviewCamera());
render();
requestAnimationFrame(() => world.classList.add("is-ready"));

const eye = document.querySelector(".eye");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function blinkEye() {
  if (reducedMotion.matches) return;
  eye.classList.remove("is-blinking");
  void eye.offsetWidth;
  eye.classList.add("is-blinking");
}

function armBlink() {
  const wait = 4000 + Math.random() * 2000;
  window.setTimeout(() => {
    blinkEye();
    if (!reducedMotion.matches) armBlink();
  }, wait);
}

if (!reducedMotion.matches) armBlink();
