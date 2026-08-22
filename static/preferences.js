/* Merco global language + currency engine.
   - Translates Merco UI text across the current page.
   - Keeps user/product supplied content out of translation when marked .user-content.
   - Adds a large language and currency catalogue.
   - Uses device/browser locale automatically, with a manual override.
   - Converts monetary values stored in the site's base currency (NGN).
*/
(function(){
  const LANGS={
    en:'English',fr:'Français',es:'Español',pt:'Português',de:'Deutsch',it:'Italiano',nl:'Nederlands',
    ar:'العربية',ha:'Hausa',yo:'Yorùbá',ig:'Igbo',sw:'Kiswahili',zu:'isiZulu',am:'አማርኛ',
    hi:'हिन्दी',bn:'বাংলা',ur:'اردو',zh:'中文',ja:'日本語',ko:'한국어',ru:'Русский',tr:'Türkçe',
    pl:'Polski',uk:'Українська',sv:'Svenska',da:'Dansk',no:'Norsk',fi:'Suomi',el:'Ελληνικά',
    he:'עברית',id:'Bahasa Indonesia',ms:'Bahasa Melayu',th:'ไทย',vi:'Tiếng Việt'
  };
  const CURRENCIES={
    NGN:'₦ Nigerian Naira',USD:'$ US Dollar',GBP:'£ British Pound',EUR:'€ Euro',GHS:'₵ Ghanaian Cedi',
    KES:'KSh Kenyan Shilling',ZAR:'R South African Rand',UGX:'USh Ugandan Shilling',TZS:'TSh Tanzanian Shilling',
    RWF:'FRw Rwandan Franc',ETB:'Br Ethiopian Birr',XOF:'CFA West African CFA Franc',XAF:'FCFA Central African CFA Franc',
    BWP:'P Botswana Pula',EGP:'E£ Egyptian Pound',MAD:'د.م. Moroccan Dirham',INR:'₹ Indian Rupee',PKR:'₨ Pakistani Rupee',
    BDT:'৳ Bangladeshi Taka',CNY:'¥ Chinese Yuan',JPY:'¥ Japanese Yen',KRW:'₩ South Korean Won',HKD:'HK$ Hong Kong Dollar',
    SGD:'S$ Singapore Dollar',MYR:'RM Malaysian Ringgit',IDR:'Rp Indonesian Rupiah',THB:'฿ Thai Baht',VND:'₫ Vietnamese Dong',
    PHP:'₱ Philippine Peso',AUD:'A$ Australian Dollar',NZD:'NZ$ New Zealand Dollar',CAD:'C$ Canadian Dollar',
    CHF:'CHF Swiss Franc',SEK:'kr Swedish Krona',NOK:'kr Norwegian Krone',DKK:'kr Danish Krone',PLN:'zł Polish Zloty',
    CZK:'Kč Czech Koruna',HUF:'Ft Hungarian Forint',TRY:'₺ Turkish Lira',RUB:'₽ Russian Ruble',UAH:'₴ Ukrainian Hryvnia',
    BRL:'R$ Brazilian Real',MXN:'MX$ Mexican Peso',ARS:'ARS Argentine Peso',CLP:'CLP Chilean Peso',COP:'COP Colombian Peso',
    AED:'د.إ UAE Dirham',SAR:'﷼ Saudi Riyal',QAR:'QAR Qatari Riyal',KWD:'د.ك Kuwaiti Dinar',ILS:'₪ Israeli Shekel'
  };
  const symbols={NGN:'₦',USD:'$',GBP:'£',EUR:'€',GHS:'₵',KES:'KSh',ZAR:'R',UGX:'USh',TZS:'TSh',RWF:'FRw',ETB:'Br',XOF:'CFA',XAF:'FCFA',BWP:'P',EGP:'E£',MAD:'د.م.',INR:'₹',PKR:'₨',BDT:'৳',CNY:'¥',JPY:'¥',KRW:'₩',HKD:'HK$',SGD:'S$',MYR:'RM',IDR:'Rp',THB:'฿',VND:'₫',PHP:'₱',AUD:'A$',NZD:'NZ$',CAD:'C$',CHF:'CHF',SEK:'kr',NOK:'kr',DKK:'kr',PLN:'zł',CZK:'Kč',HUF:'Ft',TRY:'₺',RUB:'₽',UAH:'₴',BRL:'R$',MXN:'MX$',ARS:'ARS',CLP:'CLP',COP:'COP',AED:'د.إ',SAR:'﷼',QAR:'QAR',KWD:'د.ك',ILS:'₪'};

  const core={
    Marketplace:'Marché|Mercado|Mercado|Marktplatz|Mercato|Markt|السوق|Kasu|Ọjà|Mercado|Kiswahili|አማርኛ|हिन्दी|বাংলা|اردو|市场|市場|시장|Рынок|Pazar|Rynek|Ринок|Marknad|Marked|Marked|Markkina|Αγορά|השוק|Pasar|Pasaran|ตลาด|Thị trường',
    Dashboard:'Tableau de bord|Panel|Painel|Dashboard|Pannello|Dashboard|لوحة التحكم|Allon sarrafawa|Pánẹ́ẹ̀lì|Painel|Dashibodi|ዳሽቦርድ|डैशबोर्ड|ড্যাশবোর্ড|ڈیش بورڈ|仪表板|ダッシュボード|대시보드|Панель управления|Panel|Panel|Панель|Instrumentpanel|Kontrollpanel|Kontrollpanel|Kojelauta|Πίνακας|לוח בקרה|Dasbor|Papan pemuka|แดชบอร์ด|Bảng điều khiển',
    Notifications:'Notifications|Notificaciones|Notificações|Benachrichtigungen|Notifiche|Meldingen|الإشعارات|Sanarwa|Àwọn ìfitónilétí|Notificações|Arifa|ማሳወቂያዎች|सूचनाएं|বিজ্ঞপ্তি|اطلاعات|通知|通知|알림|Уведомления|Bildirimler|Powiadomienia|Сповіщення|Aviseringar|Notifikationer|Varsler|Ilmoitukset|Ειδοποιήσεις|התראות|Notifikasi|Pemberitahuan|การแจ้งเตือน|Thông báo',
    Settings:'Paramètres|Configuración|Definições|Einstellungen|Impostazioni|Instellingen|الإعدادات|Saituna|Ètò|Definições|Mipangilio|ቅንብሮች|सेटिंग्स|সেটিংস|ترتیبات|设置|設定|설정|Настройки|Ayarlar|Ustawienia|Налаштування|Inställningar|Indstillinger|Innstillinger|Asetukset|Ρυθμίσεις|הגדרות|Pengaturan|Tetapan|การตั้งค่า|Cài đặt',
    'Log out':'Déconnexion|Cerrar sesión|Sair|Abmelden|Disconnetti|Uitloggen|تسجيل الخروج|Fita|Jáde|Sair|Ondoka|ውጣ|लॉग आउट|লগ আউট|لاگ آؤٹ|退出|ログアウト|로그아웃|Выйти|Çıkış|Wyloguj|Вийти|Logga ut|Log ud|Logg ut|Kirjaudu ulos|Αποσύνδεση|התנתק|Keluar|Log keluar|ออกจากระบบ|Đăng xuất',
    'Log in':'Connexion|Iniciar sesión|Entrar|Anmelden|Accedi|Inloggen|تسجيل الدخول|Shiga|Wọlé|Entrar|Ingia|ግባ|लॉग इन|লগ ইন|لاگ اِن|登录|ログイン|로그인|Войти|Giriş yap|Zaloguj|Увійти|Logga in|Log ind|Logg inn|Kirjaudu|Σύνδεση|התחבר|Masuk|Log masuk|เข้าสู่ระบบ|Đăng nhập',
    'Create account':'Créer un compte|Crear cuenta|Criar conta|Konto erstellen|Crea account|Account aanmaken|إنشاء حساب|Ƙirƙiri asusu|Ṣẹ̀dá àkáǹtì|Criar conta|Fungua akaunti|ፍጠር መለያ|खाता बनाएं|অ্যাকাউন্ট তৈরি করুন|اکاؤنٹ بنائیں|创建账户|アカウント作成|계정 만들기|Создать аккаунт|Hesap oluştur|Utwórz konto|Створити обліковий запис|Skapa konto|Opret konto|Opprett konto|Luo tili|Δημιουργία λογαριασμού|צור חשבון|Buat akun|Cipta akaun|สร้างบัญชี|Tạo tài khoản',
    Followers:'Abonnés|Seguidores|Seguidores|Follower|Follower|Volgers|المتابعون|Masu bi|Àwọn olùtẹ̀lé|Seguidores|Wafuasi|ተከታዮች|फ़ॉलोअर्स|অনুসারী|فالوورز|关注者|フォロワー|팔로워|Подписчики|Takipçiler|Obserwujący|Підписники|Följare|Følgere|Følgere|Seuraajat|Ακόλουθοι|עוקבים|Pengikut|Pengikut|ผู้ติดตาม|Người theo dõi',
    Analytics:'Analyses|Analítica|Análises|Analysen|Analisi|Analyses|التحليلات|Bincike|Àtúpalẹ̀|Análises|Uchambuzi|ትንታኔ|विश्लेषण|বিশ্লেষণ|تجزیات|分析|分析|분석|Аналитика|Analiz|Analityka|Аналітика|Analys|Analyse|Analyse|Analytiikka|Αναλύσεις|Αναλύσεις|Analitik|Analitik|การวิเคราะห์|Phân tích',
    'My Store':'Ma boutique|Mi tienda|Minha loja|Mein Shop|Il mio negozio|Mijn winkel|متجري|Shagona|Ilé ìtajà mi|Minha loja|Duka yangu|የእኔ መደብር|मेरी दुकान|আমার দোকান|میری دکان|我的商店|マイストア|내 상점|Мой магазин|Mağazam|Mój sklep|Мій магазин|Min butik|Min butik|Min butikk|Oma kauppa|Το κατάστημά μου|החנות שלי|Toko saya|Kedai saya|ร้านค้าของฉัน|Cửa hàng của tôi',
    Install:'Installer|Instalar|Instalar|Installieren|Installa|Installeren|تثبيت|Sanya|Fi sí ẹrọ|Instalar|Sakinisha|ጫን|इंस्टॉल|ইনস্টল|انسٹال|安装|インストール|설치|Установить|Yükle|Zainstaluj|Встановити|Installera|Installer|Installer|Asenna|Εγκατάσταση|התקן|Pasang|Pasang|ติดตั้ง|Cài đặt'
  };

  const translations={};
  Object.keys(core).forEach(k=>{
    translations[k]={};
    const vals=core[k].split('|');
    const keys=['fr','es','pt','de','it','nl','ar','ha','yo','ig','sw','am','hi','bn','ur','zh','ja','ko','ru','tr','pl','uk','sv','da','no','fi','el','he','id','ms','th','vi'];
    keys.forEach((lang,i)=>translations[k][lang]=vals[i]||k);
  });

  function autoLanguage(){
    const browser=(navigator.language||'en').slice(0,2).toLowerCase();
    if(LANGS[browser])return browser;
    const tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'';
    const zone={'Africa/Lagos':'en','Africa/Accra':'en','Africa/Nairobi':'sw','Africa/Kigali':'sw','Europe/Paris':'fr','Europe/Madrid':'es','Europe/Lisbon':'pt','Europe/Berlin':'de','Europe/Rome':'it','Europe/Amsterdam':'nl','Asia/Tokyo':'ja','Asia/Seoul':'ko','Asia/Shanghai':'zh','Asia/Kolkata':'hi','Asia/Dhaka':'bn','Asia/Bangkok':'th','Asia/Ho_Chi_Minh':'vi','Europe/Warsaw':'pl','Europe/Istanbul':'tr','Europe/Kyiv':'uk','Africa/Addis_Ababa':'am'};
    return zone[tz]||'en';
  }
  function autoCurrency(){
    const tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'';
    const map={'Africa/Lagos':'NGN','Africa/Accra':'GHS','Africa/Nairobi':'KES','Africa/Johannesburg':'ZAR','Africa/Kampala':'UGX','Africa/Dar_es_Salaam':'TZS','Africa/Kigali':'RWF','Africa/Addis_Ababa':'ETB','Europe/London':'GBP','Europe/Paris':'EUR','Europe/Berlin':'EUR','Europe/Madrid':'EUR','Europe/Lisbon':'EUR','Asia/Kolkata':'INR','Asia/Dhaka':'BDT','Asia/Tokyo':'JPY','Asia/Shanghai':'CNY','Asia/Seoul':'KRW','Asia/Singapore':'SGD','Asia/Kuala_Lumpur':'MYR','Asia/Bangkok':'THB','Asia/Ho_Chi_Minh':'VND','Australia/Sydney':'AUD','Pacific/Auckland':'NZD','America/Toronto':'CAD','America/New_York':'USD','America/Los_Angeles':'USD','America/Sao_Paulo':'BRL','America/Mexico_City':'MXN','Asia/Dubai':'AED','Asia/Riyadh':'SAR','Asia/Jerusalem':'ILS'};
    return map[tz]||'USD';
  }

  const saved=JSON.parse(localStorage.getItem('maximise-preferences')||'{}');
  let language=saved.language&&saved.language!=='auto'?saved.language:autoLanguage();
  let currency=saved.currency||autoCurrency();
  let rate=1;
  function save(){localStorage.setItem('maximise-preferences',JSON.stringify({language,currency}));}

  function keyFor(text){
    const clean=text.replace(/\s+/g,' ').trim();
    if(translations[clean])return clean;
    return null;
  }
  function applyKnownText(){
    document.documentElement.lang=language;
    document.documentElement.dir=language==='ar'?'rtl':'ltr';
    document.querySelectorAll('[data-i18n]').forEach(el=>{const key=el.dataset.i18n;if(translations[key]&&language!=='en')el.textContent=translations[key][language]||key;else if(key)el.textContent=key;});
    document.querySelectorAll('nav a span,button,.pwa-install strong,.pwa-install span').forEach(el=>{
      if(el.dataset.i18n)return;
      const raw=(el.textContent||'').replace(/\s+/g,' ').trim();
      if(translations[raw])el.textContent=language==='en'?raw:(translations[raw][language]||raw);
    });
  }

  // Translate other static UI text nodes. User generated content is deliberately excluded.
  async function translatePage(){
    applyKnownText();
    if(language==='en')return;
    const nodes=[];const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const n=walker.currentNode,p=n.parentElement;if(!p||p.closest('.user-content,[data-no-translate],script,style,textarea,input,select,option'))continue;
      const text=n.nodeValue.replace(/\s+/g,' ').trim();
      if(!text||text.length<2||/^\d+[\d\s.,%+\-/:]*$/.test(text)||text.length>180)continue;
      if(translations[text]&&translations[text][language]){n.nodeValue=n.nodeValue.replace(text,translations[text][language]);continue;}
      if(!/^[\p{L}\p{N}][\p{L}\p{N}\s.,!?&'’()\-:/+#@]+$/u.test(text))continue;
      if(nodes.some(x=>x.text===text))continue;nodes.push({n,text});
    }
    const cache=JSON.parse(localStorage.getItem('merco-translation-cache')||'{}');
    async function one(item){
      const cacheKey=language+'|'+item.text;if(cache[cacheKey]){item.n.nodeValue=item.n.nodeValue.replace(item.text,cache[cacheKey]);return;}
      try{
        const url='https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl='+encodeURIComponent(language)+'&dt=t&q='+encodeURIComponent(item.text);
        const r=await fetch(url);if(!r.ok)return;const d=await r.json();const out=(d?.[0]||[]).map(x=>x?.[0]||'').join('');if(out){cache[cacheKey]=out;item.n.nodeValue=item.n.nodeValue.replace(item.text,out);}
      }catch(_){/* Keep original text if translation service is unavailable. */}
    }
    for(let i=0;i<nodes.length;i+=5)await Promise.all(nodes.slice(i,i+5).map(one));
    try{localStorage.setItem('merco-translation-cache',JSON.stringify(cache));}catch(_){/* storage quota */}
  }

  async function fetchRate(){
    if(currency==='NGN'){rate=1;return;}
    try{
      const r=await fetch('https://open.er-api.com/v6/latest/NGN',{cache:'force-cache'});const data=await r.json();
      if(data.result==='success'&&data.rates?.[currency])rate=Number(data.rates[currency]);
    }catch(_){
      try{const r=await fetch(`https://api.frankfurter.dev/v2/rate/NGN/${currency}`,{cache:'force-cache'});if(r.ok){const data=await r.json();if(data.rate)rate=Number(data.rate);}}catch(__){rate=1;}
    }
  }
  function convertPrices(){
    document.querySelectorAll('[data-price]').forEach(el=>{const base=Number(el.dataset.price);if(!Number.isFinite(base))return;const value=base*rate;try{el.textContent=new Intl.NumberFormat(undefined,{style:'currency',currency}).format(value)}catch(_){el.textContent=`${symbols[currency]||currency}${value.toLocaleString()}`;}});
  }

  function mount(){
    if(document.getElementById('mxPreferences'))return;
    const box=document.createElement('div');box.id='mxPreferences';box.className='mx-preferences';
    box.innerHTML=`<button class="mx-pref-toggle" aria-label="Language and currency"><i class="ri-global-line"></i></button><div class="mx-pref-panel"><div class="mx-pref-head"><div><small>DISPLAY</small><strong>Language & currency</strong></div><button class="mx-pref-close" aria-label="Close">×</button></div><label>Language<select id="mxLang"><option value="auto">Auto — device region</option>${Object.entries(LANGS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>Currency<select id="mxCurrency">${Object.entries(CURRENCIES).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><p>Changing language updates the Merco interface. Product/seller supplied text is kept original.</p></div>`;
    document.body.appendChild(box);
    const panel=box.querySelector('.mx-pref-panel');
    box.querySelector('.mx-pref-toggle').onclick=()=>panel.classList.toggle('open');
    box.querySelector('.mx-pref-close').onclick=()=>panel.classList.remove('open');
    const ls=box.querySelector('#mxLang'),cs=box.querySelector('#mxCurrency');ls.value=saved.language||'auto';cs.value=currency;
    ls.onchange=async()=>{language=ls.value==='auto'?autoLanguage():ls.value;save();await translatePage()};
    cs.onchange=async()=>{currency=cs.value;save();await fetchRate();convertPrices()};
  }

  document.addEventListener('DOMContentLoaded',async()=>{mount();await fetchRate();convertPrices();await translatePage()});
})();
