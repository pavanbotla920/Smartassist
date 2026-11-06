(function () {
  'use strict';

  function switchLanguage(selector) {
    const form = selector.form;
    if (form) form.requestSubmit();
  }

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!target || !(target instanceof HTMLSelectElement)) return;

    if (target.matches('[data-site-language]')) {
      switchLanguage(target);
      return;
    }

    if (target.matches('[data-voice-language]')) {
      const siteSelector = document.querySelector('[data-site-language]');
      if (siteSelector && siteSelector.value !== target.value) {
        siteSelector.value = target.value;
        switchLanguage(siteSelector);
      }
    }
  });
})();
