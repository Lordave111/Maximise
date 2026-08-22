/* Merco page loader: hidden by default; visible only while a real page/form navigation is pending. */
(function(){
  function ready(){
    const loader=document.getElementById('mercoPageLoader');
    if(!loader)return;
    let timer;
    const hide=()=>{loader.classList.remove('is-visible');window.clearTimeout(timer);};
    const show=()=>{loader.classList.add('is-visible');window.clearTimeout(timer);timer=window.setTimeout(hide,15000);};
    hide();
    document.querySelectorAll('a[href]').forEach(a=>a.addEventListener('click',function(e){
      if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||this.target==='_blank'||this.hasAttribute('download'))return;
      const href=this.getAttribute('href');
      if(!href||href.startsWith('#')||href.startsWith('javascript:')||this.origin!==location.origin)return;
      show();
    }));
    document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',function(){if(this.checkValidity())show();}));
    window.addEventListener('pageshow',hide);
    window.addEventListener('load',hide,{once:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();
