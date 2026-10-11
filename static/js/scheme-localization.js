(function () {
  'use strict';

  const page = document.body;
  const language = document.documentElement.lang.split('-')[0].toLowerCase();
  const failureMessage = page.dataset.translationFailureMessage;
  const queue = [];
  let activeRequests = 0;
  const observer = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        enqueue(entry.target);
      });
    }, { rootMargin: '120px' })
    : null;

  function enqueue(card) {
    if (!card || card.dataset.translationRequested) return;
    card.dataset.translationRequested = 'true';
    queue.push(card);
    processQueue();
  }

  function processQueue() {
    while (activeRequests < 2 && queue.length) {
      activeRequests += 1;
      translateScheme(queue.shift()).finally(() => {
        activeRequests -= 1;
        processQueue();
      });
    }
  }

  function showFailure(card, detail) {
    const status = card.querySelector('[data-translation-status]');
    if (!status) return;
    status.textContent = detail ? `${detail} ${failureMessage}` : failureMessage;
    status.hidden = false;
  }

  async function translateScheme(card) {
    try {
      const url = new URL(page.dataset.schemeTranslationUrl, window.location.origin);
      url.searchParams.set('scheme_id', card.dataset.schemeId);
      url.searchParams.set('lang', language);
      if (card.dataset.translationFields) {
        url.searchParams.set('fields', card.dataset.translationFields);
      }

      const response = await fetch(url.toString(), {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || failureMessage);
      }

      Object.entries(result.fields || {}).forEach(([field, value]) => {
        if (typeof value !== 'string' || !value.trim()) return;
        card.querySelectorAll(`[data-scheme-field="${field}"]`).forEach((element) => {
          element.textContent = value;
        });
      });
    } catch (error) {
      showFailure(card, error instanceof Error ? error.message : '');
    }
  }

  function observe(card) {
    if (language === 'en' || !card || !card.dataset.schemeId) return;
    if (observer) {
      observer.observe(card);
    } else {
      enqueue(card);
    }
  }

  document.querySelectorAll('[data-scheme-translation-card]').forEach(observe);
  window.SmartAssistLocalization = { observe };
})();
