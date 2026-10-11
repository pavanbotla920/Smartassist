(function () {
  'use strict';

  function switchLanguage(languageCode, selector) {
    const url = new URL(selector.dataset.setLanguageUrl, window.location.origin);
    url.searchParams.set('lang', languageCode);
    url.searchParams.set(
      'next',
      `${window.location.pathname}${window.location.search}${window.location.hash}`
    );
    window.location.assign(url.toString());
  }

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!target || !(target instanceof HTMLSelectElement)) return;

    if (target.matches('[data-site-language]')) {
      switchLanguage(target.value, target);
      return;
    }

    if (target.matches('[data-voice-language]')) {
      const siteSelector = document.querySelector('[data-site-language]');
      if (siteSelector && siteSelector.value !== target.value) {
        siteSelector.value = target.value;
        switchLanguage(target.value, siteSelector);
      }
    }
  });
})();
