(function(){
  'use strict';

  const promptEl=document.getElementById('mercoInstallPrompt');
  const installBtn=document.getElementById('mercoInstallButton');
  const laterBtn=document.getElementById('mercoInstallLater');
  const hint=document.getElementById('mercoInstallHint');
  if(!promptEl||!installBtn||!laterBtn)return;

  let deferredPrompt=null;
  const DISMISS_KEY='merco-pwa-install-dismissed';
  const DISMISS_DAYS=7;

  function isStandalone(){
    return window.matchMedia('(display-mode: standalone)').matches ||
      window.matchMedia('(display-mode: fullscreen)').matches ||
      window.navigator.standalone===true;
  }

  function wasDismissed(){
    try{
      const value=Number(localStorage.getItem(DISMISS_KEY)||0);
      return value && (Date.now()-value)<DISMISS_DAYS*86400000;
    }catch(e){return false}
  }

  function openPrompt(){
    if(isStandalone()||wasDismissed())return;
    promptEl.classList.add('is-open');
    promptEl.setAttribute('aria-hidden','false');
    document.body.classList.add('merco-install-open');
  }

  function closePrompt(saveDismiss){
    if(saveDismiss){try{localStorage.setItem(DISMISS_KEY,String(Date.now()))}catch(e){}}
    promptEl.classList.remove('is-open');
    promptEl.setAttribute('aria-hidden','true');
    document.body.classList.remove('merco-install-open');
  }

  function showManualHint(){
    hint.hidden=false;
    installBtn.innerHTML='<i class="ri-information-line"></i><span>How to install</span>';
  }

  window.addEventListener('beforeinstallprompt',function(event){
    event.preventDefault();
    deferredPrompt=event;
    installBtn.innerHTML='<i class="ri-download-cloud-2-line"></i><span>Install Merco</span>';
    if(!isStandalone()&&!wasDismissed())setTimeout(openPrompt,3500);
  });

  installBtn.addEventListener('click',async function(){
    if(deferredPrompt){
      deferredPrompt.prompt();
      try{
        const result=await deferredPrompt.userChoice;
        if(result&&result.outcome==='accepted')closePrompt(false);
        else closePrompt(true);
      }catch(e){closePrompt(true)}
      deferredPrompt=null;
      return;
    }
    showManualHint();
  });

  function closeFromUser(){closePrompt(true)}
  laterBtn.addEventListener('click',closeFromUser);
  promptEl.querySelectorAll('[data-install-close]').forEach(function(el){el.addEventListener('click',closeFromUser)});
  document.addEventListener('keydown',function(event){if(event.key==='Escape'&&promptEl.classList.contains('is-open'))closeFromUser()});

  window.addEventListener('appinstalled',function(){
    deferredPrompt=null;
    closePrompt(false);
    try{localStorage.removeItem(DISMISS_KEY)}catch(e){}
  });

  // iOS Safari does not expose beforeinstallprompt. Show the same polished prompt
  // with browser-menu instructions when the site is not already installed.
  const ios=/iphone|ipad|ipod/i.test(navigator.userAgent);
  const isSafari=/safari/i.test(navigator.userAgent)&&!/chrome|crios|android/i.test(navigator.userAgent);
  if(ios&&isSafari&&!isStandalone()&&!wasDismissed()){
    setTimeout(function(){
      showManualHint();
      openPrompt();
    },5000);
  }

  if('serviceWorker' in navigator){
    window.addEventListener('load',function(){
      navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(function(){});
    });
  }
})();