(function () {
  'use strict';

  function counts(form) {
    var qs = form.querySelectorAll('.q'), done = 0;
    qs.forEach(function (q) {
      if (q.querySelector('input[type=radio]')) {
        if (q.querySelector('input[type=radio]:checked')) done++;
      } else {
        var f = q.querySelector('.ans');
        if (f && f.value.trim()) done++;
      }
    });
    return { done: done, total: qs.length };
  }

  document.querySelectorAll('form[data-sheet]').forEach(function (form) {
    var out = form.querySelector('[data-progress]');
    function update() {
      var c = counts(form);
      if (out) out.textContent = c.done + ' of ' + c.total + ' answered';
    }
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    update();

    if (form.hasAttribute('data-confirm')) {
      form.addEventListener('submit', function (e) {
        var c = counts(form), left = c.total - c.done;
        var msg = 'You have ' + left + ' question' + (left === 1 ? '' : 's') +
                  ' without an answer. Submit anyway?';
        if (left > 0 && !window.confirm(msg)) e.preventDefault();
      });
    }
  });

  document.querySelectorAll('form[data-confirm-msg]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.getAttribute('data-confirm-msg'))) e.preventDefault();
    });
  });

  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy'), label = btn.textContent;
      function done() {
        btn.textContent = 'Copied';
        setTimeout(function () { btn.textContent = label; }, 1500);
      }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done, function () {});
      } else {
        var t = document.createElement('textarea');
        t.value = text; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); done(); } catch (e) {}
        document.body.removeChild(t);
      }
    });
  });
})();
