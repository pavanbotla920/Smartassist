/* ============================================================
   SMARTASSIST SCHEME PLATFORM — JavaScript
   Handles: filtering, search, login-check, animations, UI
   ============================================================ */

(function () {
  'use strict';

  /* -------------------------------------------------------
     GLOBALS
  ------------------------------------------------------- */
  const IS_AUTHENTICATED = document.body.dataset.authenticated === 'true';
  const LOGIN_URL        = document.body.dataset.loginUrl  || '/login/';
  const APPLY_BASE_URL   = document.body.dataset.applyBase || '/apply/';

  /* -------------------------------------------------------
     1. APPLY-NOW LOGIN GUARD
     Called by every "Apply Now" button (schemes list & detail)
  ------------------------------------------------------- */
  window.handleApplyNow = function (schemeId, applyUrl) {
    if (IS_AUTHENTICATED) {
      window.location.href = applyUrl || (APPLY_BASE_URL + schemeId + '/');
    } else {
      const target = applyUrl || (APPLY_BASE_URL + schemeId + '/');
      showLoginPrompt(target);
    }
  };

  /* -------------------------------------------------------
     2. LOGIN PROMPT MODAL
  ------------------------------------------------------- */
  let pendingRedirect = null;

  function showLoginPrompt(redirectUrl) {
    pendingRedirect = redirectUrl;
    const prompt = document.getElementById('sp-login-prompt');
    if (prompt) {
      prompt.classList.add('show');
      document.body.style.overflow = 'hidden';
    } else {
      // Fallback: direct redirect with next param
      window.location.href = LOGIN_URL + '?next=' + encodeURIComponent(redirectUrl);
    }
  }

  window.closeLoginPrompt = function () {
    const prompt = document.getElementById('sp-login-prompt');
    if (prompt) {
      prompt.classList.remove('show');
      document.body.style.overflow = '';
    }
    pendingRedirect = null;
  };

  window.goToLogin = function () {
    const next = pendingRedirect
      ? '?next=' + encodeURIComponent(pendingRedirect)
      : '';
    window.location.href = LOGIN_URL + next;
  };

  /* Close on backdrop click */
  document.addEventListener('click', function (e) {
    const prompt = document.getElementById('sp-login-prompt');
    if (prompt && e.target === prompt) {
      window.closeLoginPrompt();
    }
  });

  /* Close on Escape */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') window.closeLoginPrompt();
  });

  /* -------------------------------------------------------
     3. MOBILE HAMBURGER MENU
  ------------------------------------------------------- */
  const hamburger = document.getElementById('sp-hamburger');
  const mobileNav = document.getElementById('sp-mobile-nav');

  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', function () {
      const open = mobileNav.classList.toggle('open');
      hamburger.setAttribute('aria-expanded', open);
    });
  }

  /* -------------------------------------------------------
     4. CLIENT-SIDE LIVE SEARCH (scheme name + description)
     Runs on every keystroke in the quick-search input.
     Server-side search still handles full-page loads.
  ------------------------------------------------------- */
  const liveSearch = document.getElementById('sp-live-search');
  const schemeCards = document.querySelectorAll('.sp-scheme-card[data-scheme-name]');

  function doLiveSearch(query) {
    const q = query.trim().toLowerCase();
    let visible = 0;

    schemeCards.forEach(function (card) {
      const name = (card.dataset.schemeName || '').toLowerCase();
      const desc = (card.dataset.schemeDesc || '').toLowerCase();
      const cat  = (card.dataset.category   || '').toLowerCase();
      const match = !q || name.includes(q) || desc.includes(q) || cat.includes(q);
      card.style.display = match ? '' : 'none';
      if (match) visible++;
    });

    updateResultCount(visible);
    toggleNoResults(visible === 0 && q.length > 0);
  }

  if (liveSearch) {
    liveSearch.addEventListener('input', function () {
      doLiveSearch(liveSearch.value);
    });
  }

  /* -------------------------------------------------------
     5. RESULT COUNT UPDATER
  ------------------------------------------------------- */
  function updateResultCount(count) {
    const el = document.getElementById('sp-result-count');
    if (el) {
      el.querySelector('strong').textContent = count;
    }
  }

  function toggleNoResults(show) {
    const el = document.getElementById('sp-no-results');
    if (el) el.classList.toggle('hidden', !show);
  }

  /* -------------------------------------------------------
     6. CLIENT-SIDE FILTER CHIPS (Type: All / Central / State)
     Filters cards without page reload.
  ------------------------------------------------------- */
  const typeChips = document.querySelectorAll('[data-type-filter]');

  typeChips.forEach(function (chip) {
    chip.addEventListener('click', function (e) {
      e.preventDefault();
      const type = chip.dataset.typeFilter;

      typeChips.forEach(function (c) {
        c.classList.remove('active', 'active-green');
      });
      chip.classList.add(type === 'State' ? 'active-green' : 'active');

      let visible = 0;
      schemeCards.forEach(function (card) {
        const ct = (card.dataset.schemeType || '').toLowerCase();
        const match = !type || ct === type.toLowerCase();
        card.style.display = match ? '' : 'none';
        if (match) visible++;
      });

      updateResultCount(visible);
      toggleNoResults(visible === 0);
    });
  });

  /* -------------------------------------------------------
     7. ANIMATED COUNTER (Stats bar)
  ------------------------------------------------------- */
  function animateCounter(el) {
    const target = parseInt(el.dataset.target || el.textContent, 10);
    if (isNaN(target) || target === 0) return;

    const duration = 1200;
    const start    = performance.now();
    const from     = 0;

    function step(ts) {
      const progress = Math.min((ts - start) / duration, 1);
      const ease     = 1 - Math.pow(1 - progress, 3); // easeOutCubic
      el.textContent = Math.floor(from + (target - from) * ease);
      if (progress < 1) requestAnimationFrame(step);
      else el.textContent = target;
    }
    requestAnimationFrame(step);
  }

  /* Trigger on page load via IntersectionObserver */
  const statNums = document.querySelectorAll('.sp-stat-num[data-target]');
  if ('IntersectionObserver' in window && statNums.length) {
    const obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });
    statNums.forEach(function (el) { obs.observe(el); });
  } else {
    statNums.forEach(animateCounter);
  }

  /* -------------------------------------------------------
     8. SCROLL-IN ANIMATIONS FOR CARDS
  ------------------------------------------------------- */
  if ('IntersectionObserver' in window) {
    const cardObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry, i) {
        if (entry.isIntersecting) {
          entry.target.style.animationDelay = (i * 0.06) + 's';
          entry.target.classList.add('sp-card-visible');
          cardObs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });

    schemeCards.forEach(function (card) {
      card.style.opacity = '0';
      card.style.transform = 'translateY(20px)';
      cardObs.observe(card);
    });

    /* Inject style for the class */
    const style = document.createElement('style');
    style.textContent = `.sp-card-visible{opacity:1!important;transform:translateY(0)!important;transition:opacity 0.5s ease,transform 0.5s ease;}`;
    document.head.appendChild(style);
  }

  /* -------------------------------------------------------
     9. TOAST NOTIFICATIONS
  ------------------------------------------------------- */
  window.showToast = function (message, title, type) {
    let toast = document.getElementById('sp-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'sp-toast';
      toast.className = 'sp-toast';
      toast.innerHTML = '<span class="sp-toast-icon"></span><div class="sp-toast-msg"><strong></strong><span></span></div>';
      document.body.appendChild(toast);
    }

    const icons = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };
    toast.querySelector('.sp-toast-icon').textContent = icons[type] || icons.info;
    toast.querySelector('.sp-toast-msg strong').textContent = title || '';
    toast.querySelector('.sp-toast-msg span').textContent = message || '';

    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () {
      toast.classList.remove('show');
    }, 4000);
  };

  /* -------------------------------------------------------
     10. SIDEBAR FILTER: STATE SEARCH
  ------------------------------------------------------- */
  const stateSearchInput = document.getElementById('sp-state-search');
  if (stateSearchInput) {
    stateSearchInput.addEventListener('input', function () {
      const q = stateSearchInput.value.toLowerCase();
      document.querySelectorAll('.sp-filter-option[data-state-option]').forEach(function (opt) {
        const state = (opt.dataset.stateOption || '').toLowerCase();
        opt.style.display = !q || state.includes(q) ? '' : 'none';
      });
    });
  }

  /* -------------------------------------------------------
     11. ACTIVE NAV LINK
  ------------------------------------------------------- */
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sp-nav-link').forEach(function (link) {
    if (link.getAttribute('href') && currentPath.startsWith(link.getAttribute('href')) &&
        link.getAttribute('href') !== '/') {
      link.classList.add('active');
    }
  });

  /* -------------------------------------------------------
     12. SCHEME DETAIL: BACK BUTTON WITH HISTORY
  ------------------------------------------------------- */
  const backBtn = document.getElementById('sp-back-btn');
  if (backBtn) {
    backBtn.addEventListener('click', function (e) {
      if (document.referrer && document.referrer.includes(window.location.host)) {
        e.preventDefault();
        history.back();
      }
    });
  }

  /* -------------------------------------------------------
     13. FILTER FORM AUTO-SUBMIT ON SELECT CHANGE
  ------------------------------------------------------- */
  const filterForm = document.getElementById('sp-filter-form');
  if (filterForm) {
    filterForm.querySelectorAll('select').forEach(function (sel) {
      sel.addEventListener('change', function () {
        filterForm.submit();
      });
    });
  }

  /* -------------------------------------------------------
     14. SEARCH BAR: Submit on Enter
  ------------------------------------------------------- */
  const heroSearchInput = document.getElementById('sp-search-input');
  if (heroSearchInput) {
    heroSearchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        const form = heroSearchInput.closest('form');
        if (form) form.submit();
      }
    });
  }

  /* -------------------------------------------------------
     15. LANGUAGE SWITCHER DROPDOWN
  ------------------------------------------------------- */
  var langToggle = document.getElementById('sp-lang-toggle');
  var langDropdown = document.getElementById('sp-lang-dropdown');

  if (langToggle && langDropdown) {
    langToggle.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = langDropdown.classList.toggle('open');
      langToggle.setAttribute('aria-expanded', open);
    });

    document.addEventListener('click', function (e) {
      if (!langDropdown.contains(e.target) && e.target !== langToggle) {
        langDropdown.classList.remove('open');
        langToggle.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        langDropdown.classList.remove('open');
        langToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* -------------------------------------------------------
     16. SCHEME DETAILS MODAL (no external library required)
  ------------------------------------------------------- */
  function ensureDetailsModal() {
    let modal = document.getElementById('sp-details-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'sp-details-modal';
    modal.className = 'sp-details-modal';
    modal.innerHTML = [
      '<div class="sp-details-dialog" role="dialog" aria-modal="true" aria-labelledby="sp-details-title">',
      '  <button type="button" class="sp-details-close" aria-label="Close details">✕</button>',
      '  <div class="sp-details-head">',
      '    <h3 id="sp-details-title"></h3>',
      '    <div class="sp-details-badges" id="sp-details-badges"></div>',
      '  </div>',
      '  <div class="sp-details-body" id="sp-details-body"></div>',
      '  <div class="sp-details-actions">',
      '    <button type="button" class="sp-details-btn-secondary" data-action="close">Close</button>',
      '    <a href="#" class="sp-details-btn-primary" id="sp-details-apply">Apply Now</a>',
      '  </div>',
      '</div>'
    ].join('');

    document.body.appendChild(modal);

    const closeModal = function () {
      modal.classList.remove('show');
      document.body.style.overflow = '';
    };

    modal.addEventListener('click', function (e) {
      if (e.target === modal || e.target.dataset.action === 'close' || e.target.classList.contains('sp-details-close')) {
        closeModal();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('show')) {
        closeModal();
      }
    });

    return modal;
  }

  window.showSchemeDetails = function (schemeId) {
    const card = document.querySelector('.sp-scheme-card[data-scheme-id="' + schemeId + '"]');
    if (!card) {
      window.showToast('Unable to load scheme details right now.', 'Not found', 'warning');
      return;
    }

    const modal = ensureDetailsModal();
    const title = card.dataset.schemeTitle || 'Scheme Details';
    const desc = card.dataset.schemeDesc || 'No description available.';
    const type = card.dataset.schemeType || 'N/A';
    const state = card.dataset.state || 'N/A';
    const category = card.dataset.category || 'N/A';
    const dept = card.dataset.department || 'Not specified';
    const minAge = card.dataset.minAge;
    const maxAge = card.dataset.maxAge;
    const incomeLimit = card.dataset.incomeLimit;
    const officialWebsite = card.dataset.officialWebsite || card.dataset.applyLink || '';

    modal.querySelector('#sp-details-title').textContent = title;

    const badges = [
      '<span class="sp-details-badge">' + type + '</span>',
      '<span class="sp-details-badge">' + state + '</span>'
    ];
    if (category && category !== 'all') badges.push('<span class="sp-details-badge">' + category + '</span>');
    modal.querySelector('#sp-details-badges').innerHTML = badges.join('');

    const eligibility = [];
    if (minAge || maxAge) {
      eligibility.push('<li><strong>Age:</strong> ' + (minAge || '-') + ' - ' + (maxAge || '-') + ' years</li>');
    }
    if (incomeLimit) {
      eligibility.push('<li><strong>Income:</strong> <= Rs ' + incomeLimit + ' / year</li>');
    }

    modal.querySelector('#sp-details-body').innerHTML = [
      '<p>' + desc + '</p>',
      '<p><strong>Department:</strong> ' + dept + '</p>',
      eligibility.length ? '<div><strong>Eligibility</strong><ul>' + eligibility.join('') + '</ul></div>' : '',
      officialWebsite ? '<p><a href="' + officialWebsite + '" target="_blank" rel="noopener noreferrer">Visit official website</a></p>' : ''
    ].join('');

    const applyUrl = APPLY_BASE_URL + schemeId + '/';
    const applyLink = modal.querySelector('#sp-details-apply');
    applyLink.setAttribute('href', applyUrl);
    applyLink.onclick = function (e) {
      e.preventDefault();
      window.handleApplyNow(schemeId, applyUrl);
    };

    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
  };

})();
