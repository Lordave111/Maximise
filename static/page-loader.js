/* Merco page loader + offline reconnect state. */
(function(){
  function ready(){
    const loader=document.getElementById('mercoPageLoader');
    const offline=document.getElementById('mercoOffline');
    const reconnect=document.getElementById('mercoReconnect');
    let timer;

    if(loader){
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

    if(offline){
      const setOffline=(isOffline)=>{
        offline.classList.toggle('is-visible',isOffline);
        offline.setAttribute('aria-hidden',String(!isOffline));
      };
      setOffline(!navigator.onLine);
      window.addEventListener('offline',()=>setOffline(true));
      window.addEventListener('online',()=>setOffline(false));
      reconnect?.addEventListener('click',()=>{
        if(navigator.onLine){
          offline.classList.add('is-checking');
          window.location.reload();
        }else{
          offline.classList.remove('is-pulse');
          void offline.offsetWidth;
          offline.classList.add('is-pulse');
        }
      });
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();
