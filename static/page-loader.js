/* Merco page loader: visible only while the browser is loading/navigating. */
(function(){
  function ready(){
    const loader=document.getElementById('mercoPageLoader');
    if(!loader)return;
    loader.classList.add('is-hidden');
    const show=()=>loader.classList.remove('is-hidden');
    document.querySelectorAll('a[href]').forEach(a=>a.addEventListener('click',function(e){
      if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||this.target==='_blank'||this.hasAttribute('download'))return;
      const href=this.getAttribute('href');
      if(!href||href.startsWith('#')||href.startsWith('javascript:')||this.origin!==location.origin)return;
      show();
    }));
    document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',()=>show()));
    window.addEventListener('pageshow',()=>loader.classList.add('is-hidden'));
    window.addEventListener('beforeunload',show);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();
