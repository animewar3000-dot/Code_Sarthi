const carousel=document.querySelector('.hero-visual');
const track=document.querySelector('#hero-carousel-track');
const slides=[...document.querySelectorAll('.carousel-slide')];
const dots=[...document.querySelectorAll('.carousel-dot')];
const counter=document.querySelector('#carousel-count');
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
let currentSlide=0;
let carouselTimer=null;

function showSlide(index){
  currentSlide=(index+slides.length)%slides.length;
  track.style.setProperty('--slide-index',currentSlide);
  slides.forEach((slide,i)=>{
    slide.classList.toggle('is-active',i===currentSlide);
    slide.setAttribute('aria-hidden',String(i!==currentSlide));
  });
  dots.forEach((dot,i)=>{
    dot.classList.toggle('is-active',i===currentSlide);
    if(i===currentSlide)dot.setAttribute('aria-current','true');
    else dot.removeAttribute('aria-current');
  });
  counter.textContent=`0${currentSlide+1} / 0${slides.length}`;
}

function stopAutoAdvance(){if(carouselTimer){clearInterval(carouselTimer);carouselTimer=null;}}
function updateAutoAdvance(){
  stopAutoAdvance();
  const animations=[...document.querySelectorAll('.carousel-slide svg')];
  if(reducedMotion.matches){animations.forEach(svg=>svg.pauseAnimations?.());return;}
  animations.forEach(svg=>svg.unpauseAnimations?.());
  if(!carousel.matches(':hover,:focus-within')&&!document.hidden){
    carouselTimer=setInterval(()=>showSlide(currentSlide+1),7000);
  }
}

document.querySelector('[data-carousel="previous"]').addEventListener('click',()=>{showSlide(currentSlide-1);updateAutoAdvance();});
document.querySelector('[data-carousel="next"]').addEventListener('click',()=>{showSlide(currentSlide+1);updateAutoAdvance();});
dots.forEach(dot=>dot.addEventListener('click',()=>{showSlide(Number(dot.dataset.slideTo));updateAutoAdvance();}));
carousel.addEventListener('mouseenter',stopAutoAdvance);
carousel.addEventListener('mouseleave',updateAutoAdvance);
carousel.addEventListener('focusin',stopAutoAdvance);
carousel.addEventListener('focusout',event=>{if(!carousel.contains(event.relatedTarget))updateAutoAdvance();});
carousel.addEventListener('keydown',event=>{
  if(event.key==='ArrowLeft'){event.preventDefault();showSlide(currentSlide-1);updateAutoAdvance();}
  if(event.key==='ArrowRight'){event.preventDefault();showSlide(currentSlide+1);updateAutoAdvance();}
});
document.addEventListener('visibilitychange',updateAutoAdvance);
reducedMotion.addEventListener?.('change',updateAutoAdvance);
showSlide(0);
updateAutoAdvance();
