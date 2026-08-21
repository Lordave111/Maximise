/* Maximise language + currency preferences. Uses device locale/timezone for the automatic choice. */
(function(){
  const LANGS={en:'English',fr:'Français',es:'Español',pt:'Português',ar:'العربية',ha:'Hausa',yo:'Yorùbá'};
  const CURRENCIES={NGN:'₦ Nigerian Naira',USD:'$ US Dollar',GBP:'£ British Pound',EUR:'€ Euro',GHS:'₵ Ghanaian Cedi',KES:'KSh Kenyan Shilling',ZAR:'R South African Rand'};
  const symbols={NGN:'₦',USD:'$',GBP:'£',EUR:'€',GHS:'₵',KES:'KSh',ZAR:'R'};
  const translations={
    fr:{Marketplace:'Marché',Dashboard:'Tableau de bord',Notifications:'Notifications',Settings:'Paramètres','Log out':'Déconnexion','Log in':'Connexion','Create account':'Créer un compte','Following Sellers':'Vendeurs suivis',Followers:'Abonnés',Analytics:'Analyses','My Store':'Ma boutique',Install:'Installer'},
    es:{Marketplace:'Mercado',Dashboard:'Panel',Notifications:'Notificaciones',Settings:'Configuración','Log out':'Cerrar sesión','Log in':'Iniciar sesión','Create account':'Crear cuenta','Following Sellers':'Vendedores seguidos',Followers:'Seguidores',Analytics:'Analítica','My Store':'Mi tienda',Install:'Instalar'},
    pt:{Marketplace:'Mercado',Dashboard:'Painel',Notifications:'Notificações',Settings:'Definições','Log out':'Sair','Log in':'Entrar','Create account':'Criar conta',Followers:'Seguidores',Analytics:'Análises','My Store':'Minha loja',Install:'Instalar'},
    ar:{Marketplace:'السوق',Dashboard:'لوحة التحكم',Notifications:'الإشعارات',Settings:'الإعدادات','Log out':'تسجيل الخروج','Log in':'تسجيل الدخول','Create account':'إنشاء حساب',Followers:'المتابعون',Analytics:'التحليلات','My Store':'متجري',Install:'تثبيت'},
    ha:{Marketplace:'Kasu',Dashboard:'Allon sarrafawa',Notifications:'Sanarwa',Settings:'Saituna','Log out':'Fita','Log in':'Shiga','Create account':'Ƙirƙiri asusu',Followers:'Masu bi',Analytics:'Bincike','My Store':'Shagona',Install:'Sanya'},
    yo:{Marketplace:'Ọjà',Dashboard:'Pánẹ́ẹ̀lì',Notifications:'Àwọn ìfitónilétí',Settings:'Ètò','Log out':'Jáde','Log in':'Wọlé','Create account':'Ṣẹ̀dá àkáǹtì',Followers:'Àwọn olùtẹ̀lé',Analytics:'Àtúpalẹ̀','My Store':'Ilé ìtajà mi',Install:'Fi sí ẹrọ'}
  };
  function autoLanguage(){
    const browser=(navigator.language||'en').slice(0,2).toLowerCase();
    if(['fr','es','pt','ar','ha','yo'].includes(browser)) return browser;
    return 'en';
  }
  function autoCurrency(){
    const tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'';
    const map={'Africa/Lagos':'NGN','Africa/Accra':'GHS','Africa/Nairobi':'KES','Africa/Johannesburg':'ZAR','Europe/London':'GBP','Europe/Paris':'EUR','Europe/Madrid':'EUR','Europe/Lisbon':'EUR'};
    return map[tz]||'USD';
  }
  const saved=JSON.parse(localStorage.getItem('maximise-preferences')||'{}');
  let language=saved.language&&saved.language!=='auto'?saved.language:autoLanguage();
  let currency=saved.currency||autoCurrency();
  let rate=1;
  function save(){localStorage.setItem('maximise-preferences',JSON.stringify({language,currency}));}
  function applyLanguage(){
    document.documentElement.lang=language;
    document.documentElement.dir=language==='ar'?'rtl':'ltr';
    const dict=translations[language]||{};
    document.querySelectorAll('nav a span,button,.pwa-install strong,.pwa-install span').forEach(el=>{const raw=(el.dataset.i18n||el.textContent||'').trim();if(dict[raw])el.textContent=dict[raw];});
  }
  async function fetchRate(){
    if(currency==='NGN'){rate=1;return;}
    try{const r=await fetch(`https://api.frankfurter.dev/v2/rate/NGN/${currency}`,{cache:'force-cache'});if(r.ok){const data=await r.json();if(data.rate)rate=Number(data.rate);}}catch(_){rate=1;}
  }
  function convertPrices(){
    document.querySelectorAll('[data-price]').forEach(el=>{const base=Number(el.dataset.price);if(!Number.isFinite(base))return;const value=base*rate;try{el.textContent=new Intl.NumberFormat(undefined,{style:'currency',currency}).format(value)}catch(_){el.textContent=`${symbols[currency]||currency}${value.toLocaleString()}`;}});
  }
  function mount(){
    if(document.getElementById('mxPreferences'))return;
    const box=document.createElement('div');box.id='mxPreferences';box.className='mx-preferences';
    box.innerHTML=`<button class="mx-pref-toggle" aria-label="Language and currency"><i class="ri-global-line"></i></button><div class="mx-pref-panel"><div class="mx-pref-head"><div><small>DISPLAY</small><strong>Language & currency</strong></div><button class="mx-pref-close" aria-label="Close">×</button></div><label>Language<select id="mxLang"><option value="auto">Auto — device region</option>${Object.entries(LANGS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>Currency<select id="mxCurrency">${Object.entries(CURRENCIES).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><p>Automatic mode uses your browser language and device time zone. You can always override it.</p></div>`;
    document.body.appendChild(box);
    const panel=box.querySelector('.mx-pref-panel');
    box.querySelector('.mx-pref-toggle').onclick=()=>panel.classList.toggle('open');
    box.querySelector('.mx-pref-close').onclick=()=>panel.classList.remove('open');
    const ls=box.querySelector('#mxLang'),cs=box.querySelector('#mxCurrency');
    ls.value=saved.language||'auto';cs.value=currency;
    ls.onchange=()=>{language=ls.value==='auto'?autoLanguage():ls.value;save();applyLanguage()};
    cs.onchange=async()=>{currency=cs.value;save();await fetchRate();convertPrices()};
  }
  document.addEventListener('DOMContentLoaded',async()=>{mount();applyLanguage();await fetchRate();convertPrices()});
})();
