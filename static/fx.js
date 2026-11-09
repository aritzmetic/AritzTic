/* shared helpers + effects (used by host.html and view.html) */
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe=u=>/^(https?:\/\/|data:image\/)/i.test(u||'')?u:'#';
const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('on');setTimeout(()=>t.classList.remove('on'),2400)};
const api=async(u,m='GET',b)=>{const f=b instanceof FormData;const r=await fetch(u,{method:m,headers:f||!b?{}:{'Content-Type':'application/json'},body:f?b:b&&JSON.stringify(b)});if(!r.ok)throw new Error(r.status);return r.json()};
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.1});
const reveal=()=>$$('.rv:not(.in)').forEach(e=>io.observe(e));
const count=(el,to)=>{const s=+el.textContent,t0=performance.now();(function f(t){const k=Math.min(1,(t-t0)/900);el.textContent=Math.round(s+(to-s)*k);if(k<1)requestAnimationFrame(f)})(t0)};
const card=(p,extra='')=>`<article class="card rv" data-id="${p.id}" tabindex="0"><div class="thumb">${p.images[0]?`<img loading="lazy" alt="${esc(p.title)}" src="${esc(safe(p.images[0]))}">`:`<b>${esc(p.title[0]||'?')}</b>`}${p.featured?'<span class="star">★ Featured</span>':''}</div>
<div class="cb"><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><div class="tags">${p.tags.map(t=>`<span>${esc(t)}</span>`).join('')}</div><div class="meta"><span>👁 ${p.views}</span><span>♥ ${p.likes}</span></div>${extra}</div></article>`;
const shrink=f=>new Promise(r=>{const i=new Image();i.onload=()=>{const k=Math.min(1,900/Math.max(i.width,i.height)),c=document.createElement('canvas');c.width=i.width*k;c.height=i.height*k;c.getContext('2d').drawImage(i,0,0,c.width,c.height);r(c.toDataURL('image/jpeg',.7))};i.src=URL.createObjectURL(f)});
function fx(){
 document.body.insertAdjacentHTML('afterbegin','<div id="prog"></div><canvas id="bg"></canvas><div id="cd"></div><div id="cr"></div><div id="toast"></div>');
 let mx=innerWidth/2,my=innerHeight/2,rx=mx,ry=my;
 addEventListener('mousemove',e=>{mx=e.clientX;my=e.clientY;$('#cd').style.transform=`translate(${mx}px,${my}px)`});
 (function ring(){rx+=(mx-rx)*.15;ry+=(my-ry)*.15;$('#cr').style.transform=`translate(${rx}px,${ry}px)`;requestAnimationFrame(ring)})();
 document.addEventListener('mouseover',e=>$('#cr').classList.toggle('hot',!!e.target.closest('a,button,.card,.chip,label')));
 addEventListener('scroll',()=>{$('#prog').style.width=scrollY/Math.max(1,document.body.scrollHeight-innerHeight)*100+'%'},{passive:true});
 document.addEventListener('mousemove',e=>{const c=e.target.closest('.card');if(c){const r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;c.style.transform=`rotateY(${(x-.5)*12}deg) rotateX(${(.5-y)*12}deg) translateZ(8px)`;c.style.setProperty('--mx',x*100+'%');c.style.setProperty('--my',y*100+'%')}
  const m=e.target.closest('.mag');$$('.mag').forEach(b=>{if(b!==m)b.style.transform=''});if(m){const r=m.getBoundingClientRect();m.style.transform=`translate(${(e.clientX-r.left-r.width/2)*.25}px,${(e.clientY-r.top-r.height/2)*.35}px)`}});
 document.addEventListener('mouseout',e=>{const c=e.target.closest('.card');if(c)c.style.transform=''});
 const cv=$('#bg'),cx=cv.getContext('2d');let P=[];
 const fit=()=>{cv.width=innerWidth;cv.height=innerHeight;P=Array.from({length:Math.min(90,innerWidth/14|0)},()=>({x:Math.random()*cv.width,y:Math.random()*cv.height,vx:(Math.random()-.5)*.4,vy:(Math.random()-.5)*.4,r:Math.random()*1.8+.6}))};addEventListener('resize',fit);fit();
 (function draw(){cx.clearRect(0,0,cv.width,cv.height);for(const p of P){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>cv.width)p.vx*=-1;if(p.y<0||p.y>cv.height)p.vy*=-1;
  const dx=p.x-mx,dy=p.y-my,d=Math.hypot(dx,dy);if(d<140){p.x+=dx/d*1.6;p.y+=dy/d*1.6;cx.strokeStyle=`rgba(255,106,0,${1-d/140})`;cx.beginPath();cx.moveTo(p.x,p.y);cx.lineTo(mx,my);cx.stroke()}
  cx.fillStyle='#ff6a00aa';cx.beginPath();cx.arc(p.x,p.y,p.r,0,7);cx.fill()}requestAnimationFrame(draw)})();
}
async function typeLoop(el,get){let w='',d=false,i=0;for(;;){const r=get(),t=r[i%r.length]||'';w=d?t.slice(0,w.length-1):t.slice(0,w.length+1);el.textContent=w;
 if(!d&&w===t){d=true;await new Promise(r=>setTimeout(r,1500))}else if(d&&!w){d=false;i++}await new Promise(r=>setTimeout(r,d?35:80))}}
