/* 慧农 AI · 通用交互：移动端抽屉菜单、图片上传/拍照、拖拽、防重复提交 */
(function () {
  'use strict';

  /* ---------- 侧边汉堡菜单 ---------- */
  var menuBtn = document.getElementById('menuBtn');
  var drawer = document.getElementById('drawer');
  var mask = document.getElementById('drawerMask');
  var closeBtn = document.getElementById('drawerClose');

  function openDrawer() {
    if (!drawer) return;
    drawer.classList.add('show');
    mask.classList.add('show');
    document.body.style.overflow = 'hidden';
  }
  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove('show');
    mask.classList.remove('show');
    document.body.style.overflow = '';
  }
  if (menuBtn) menuBtn.addEventListener('click', openDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  if (mask) mask.addEventListener('click', closeDrawer);
  if (drawer) {
    drawer.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', closeDrawer);
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeDrawer();
  });

  /* ---------- 图片上传 / 拍照 ---------- */
  var zone = document.getElementById('uploadZone');
  var input = document.getElementById('imageInput');
  var preview = document.getElementById('previewBox');
  var previewImg = document.getElementById('previewImg');
  var pickBtn = document.getElementById('pickBtn');
  var cameraBtn = document.getElementById('cameraBtn');

  function showPreview(src) {
    if (!preview) return;
    previewImg.src = src;
    preview.classList.add('show');
  }

  function pickImage(useCamera) {
    if (!input) return;
    // 移动端通过 capture="environment" 直接唤起后置摄像头，PC 端等同于普通选择文件
    if (useCamera) {
      input.setAttribute('capture', 'environment');
    } else {
      input.removeAttribute('capture');
    }
    input.value = '';
    input.click();
  }

  if (zone) zone.addEventListener('click', function () { pickImage(false); });
  if (pickBtn) pickBtn.addEventListener('click', function (e) { e.stopPropagation(); pickImage(false); });
  if (cameraBtn) cameraBtn.addEventListener('click', function (e) { e.stopPropagation(); pickImage(true); });

  if (input) {
    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      if (!f) return;
      if (f.size > 8 * 1024 * 1024) {
        alert('图片超过 8MB，请压缩后再上传');
        input.value = '';
        return;
      }
      var reader = new FileReader();
      reader.onload = function (ev) { showPreview(ev.target.result); };
      reader.readAsDataURL(f);
      var tip = document.getElementById('fileName');
      if (tip) tip.textContent = '已选择：' + f.name;
      var submit = document.getElementById('submitBtn');
      if (submit) {
        submit.disabled = false;
      }
    });
  }

  if (zone) {
    ['dragenter', 'dragover'].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.add('drag');
      });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.remove('drag');
      });
    });
    zone.addEventListener('drop', function (e) {
      if (input && e.dataTransfer.files && e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        var evt = new Event('change');
        input.dispatchEvent(evt);
      }
    });
  }

  /* ---------- 提交时防重复点击 ---------- */
  document.querySelectorAll('form[data-loading]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var btn = form.querySelector('[type=submit]');
      if (btn) {
        btn.disabled = true;
        btn.dataset.text = btn.textContent;
        btn.textContent = '识别中…';
      }
    });
  });

  /* ---------- 首页景观轮播（画面 + 政策响应） ---------- */
  (function () {
    var wrap = document.getElementById('showcase');
    if (!wrap) return;
    var slides = wrap.querySelectorAll('.sc-slide');
    var dots = wrap.querySelectorAll('.sc-dot');
    if (!slides.length) return;

    var eyeText = document.getElementById('scEyeText');
    var eyeIcon = document.getElementById('scEyeIcon');
    var policy = document.getElementById('scPolicy');

    var DATA = [
      { eye: '绿水青山 · 生态优先', icon: 'i-leaf',
        title: '绿水青山就是金山银山',
        desc: '坚持生态优先、绿色发展，让良好生态成为乡村振兴的重要支撑' },
      { eye: '麦浪滚滚 · 粮食安全', icon: 'i-wheat',
        title: '藏粮于地、藏粮于技',
        desc: '严守耕地红线，把中国人的饭碗牢牢端在自己手中' },
      { eye: '智慧农业 · 科技赋能', icon: 'i-spark',
        title: '因地制宜发展农业新质生产力',
        desc: '推动人工智能、大数据与农业生产深度融合，让农业从「看天吃饭」转向「知天而作」' },
      { eye: '丰收田野 · 乡村振兴', icon: 'i-basket',
        title: '全面推进乡村振兴',
        desc: '产业兴旺、农民增收，拓宽农产品销售渠道，让好产品卖出好价钱' }
    ];

    var DURATION = 7000;
    var idx = 0;
    var timer = null;

    function render(i) {
      for (var n = 0; n < slides.length; n++) {
        slides[n].classList.toggle('is-active', n === i);
      }
      for (var m = 0; m < dots.length; m++) {
        dots[m].classList.toggle('is-active', m === i);
      }
      var d = DATA[i] || DATA[0];
      if (eyeText) eyeText.textContent = d.eye;
      if (eyeIcon) eyeIcon.setAttribute('href', '#' + d.icon);
      if (policy) {
        var b = policy.querySelector('b');
        var s = policy.querySelector('span');
        if (b) b.textContent = d.title;
        if (s) s.textContent = d.desc;
      }
    }

    function schedule() {
      if (timer) clearInterval(timer);
      timer = setInterval(function () { go(idx + 1); }, DURATION);
    }

    function go(i) {
      idx = (i % slides.length + slides.length) % slides.length;
      render(idx);
      schedule();
    }

    for (var k = 0; k < dots.length; k++) {
      dots[k].addEventListener('click', function () {
        go(parseInt(this.getAttribute('data-i'), 10));
      });
    }

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        if (timer) clearInterval(timer);
      } else {
        schedule();
      }
    });

    render(0);
    schedule();
  })();
})();

/* ---------- 开场动画：进站自动播放，可跳过 ---------- */
(function () {
  var overlay = document.getElementById('introOverlay');
  var video = document.getElementById('introVideo');
  var skipBtn = document.getElementById('introSkip');
  var countEl = document.getElementById('introCount');
  var ring = document.getElementById('introRing');
  var bar = document.getElementById('introBar');
  var replay = document.getElementById('replayIntro');
  if (!overlay || !video) return;

  var KEY = 'hn_intro_done';
  var RING_LEN = 119.4;          // 2πr, r=19
  var MAX_WAIT = 9000;           // 兜底：最长 9 秒
  var timer = null, raf = null, finished = false;

  function setProgress(p) {
    p = Math.max(0, Math.min(1, p));
    if (bar) bar.style.width = (p * 100) + '%';
    if (ring) ring.style.strokeDashoffset = (RING_LEN * (1 - p)).toFixed(1);
  }

  function tick() {
    var d = video.duration || 5;
    var t = video.currentTime || 0;
    setProgress(t / d);
    var left = Math.max(0, Math.ceil(d - t));
    if (countEl) countEl.textContent = left;
    raf = requestAnimationFrame(tick);
  }

  function finish() {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
    setProgress(1);
    overlay.classList.remove('is-open');
    overlay.classList.add('is-out');
    document.body.style.overflow = '';
    try { sessionStorage.setItem(KEY, '1'); } catch (e) {}
    setTimeout(function () {
      video.pause();
      overlay.hidden = true;
      overlay.classList.remove('is-out');
    }, 580);
  }

  function start() {
    finished = false;
    clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
    // 按屏幕方向选择片源：横屏设备用 16:9 版，竖屏（手机）用 9:16 版
    var wide = window.innerWidth >= window.innerHeight;
    var src = wide ? overlay.dataset.srcWide : overlay.dataset.srcTall;
    if (src && video.getAttribute('src') !== src) video.setAttribute('src', src);
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
    // 强制回流后再加 class，保证淡入过渡生效
    void overlay.offsetWidth;
    overlay.classList.add('is-open');
    video.currentTime = 0;
    var p = video.play();
    if (p && p.catch) {
      p.catch(function () {           // 自动播放被拦截时直接跳过，不挡路
        video.muted = true;
        var p2 = video.play();
        if (p2 && p2.catch) p2.catch(function () { finish(); });
      });
    }
    raf = requestAnimationFrame(tick);
    timer = setTimeout(finish, MAX_WAIT);
  }

  if (skipBtn) skipBtn.addEventListener('click', function (e) { e.stopPropagation(); finish(); });
  overlay.addEventListener('click', finish);
  document.addEventListener('keydown', function (e) {
    if (!overlay.hidden && (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ')) finish();
  });
  video.addEventListener('ended', finish);
  video.addEventListener('error', finish);

  if (replay) replay.addEventListener('click', function () { start(); });

  // 每个浏览会话播放一次（换标签页会重新播放，便于演示）
  var seen = false;
  try { seen = sessionStorage.getItem(KEY) === '1'; } catch (e) {}
  if (!seen) start();
})();
