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
  function sameOriginHttpUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, window.location.origin);
      if (!['http:', 'https:'].includes(url.protocol) || url.origin !== window.location.origin) {
        return null;
      }
      return url.href;
    } catch (error) {
      return null;
    }
  }

  function positiveSchemeId(value) {
    const id = String(value ?? '');
    return /^\d+$/.test(id) && Number(id) > 0 && Number.isSafeInteger(Number(id))
      ? id
      : null;
  }

  const LOGIN_URL        = sameOriginHttpUrl(document.body.dataset.loginUrl) || new URL('/login/', window.location.origin).href;
  const APPLY_BASE_URL   = sameOriginHttpUrl(document.body.dataset.applyBase) || new URL('/apply/', window.location.origin).href;

  function defaultApplicationUrl(schemeId) {
    return sameOriginHttpUrl(APPLY_BASE_URL + schemeId + '/');
  }

  /* -------------------------------------------------------
     1. APPLY-NOW LOGIN GUARD
     Called by every "Apply Now" button (schemes list & detail)
  ------------------------------------------------------- */
  window.handleApplyNow = function (schemeId, applyUrl) {
    const validSchemeId = positiveSchemeId(schemeId);
    const fallbackUrl = validSchemeId ? defaultApplicationUrl(validSchemeId) : null;
    const target = sameOriginHttpUrl(applyUrl) || fallbackUrl;
    if (!target) {
      window.showToast('Unable to load scheme details right now.', 'Not found', 'warning');
      return;
    }

    if (IS_AUTHENTICATED) {
      window.location.href = target;
    } else {
      showLoginPrompt(target);
    }
  };

  /* -------------------------------------------------------
     2. LOGIN PROMPT MODAL
  ------------------------------------------------------- */
  let pendingRedirect = null;

  function showLoginPrompt(redirectUrl) {
    pendingRedirect = sameOriginHttpUrl(redirectUrl);
    if (!pendingRedirect) {
      window.showToast('Unable to load scheme details right now.', 'Not found', 'warning');
      return;
    }
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
  const mainSearch = document.getElementById('sp-search-input');
  const schemeCards = document.querySelectorAll('.sp-scheme-card[data-scheme-name]');
  const resultsGrid = document.getElementById('sp-schemes-grid');
  const hasServerStateFilter = Boolean(
    resultsGrid && resultsGrid.dataset.stateFilter
  );

  // Browser autofill can restore the instant-search field after a reload.
  // Never let that stale client-side value hide a fresh server-side state result.
  if (hasServerStateFilter && liveSearch) {
    liveSearch.value = '';
  }

  function doLiveSearch(query) {
    const q = query.trim().toLowerCase().replace(/[-_/]+/g, ' ').replace(/\s+/g, ' ');
    const terms = q ? q.split(' ') : [];
    let visible = 0;

    schemeCards.forEach(function (card) {
      const searchableText = [
        card.dataset.schemeName,
        card.dataset.schemeDesc,
        card.dataset.schemeBenefits,
        card.dataset.schemeEligibility,
        card.dataset.department,
        card.dataset.category,
        card.dataset.state,
        card.dataset.schemeType,
        card.textContent
      ].join(' ').toLowerCase().replace(/[-_/]+/g, ' ').replace(/\s+/g, ' ');
      const match = !terms.length || terms.every(function (term) {
        return searchableText.includes(term);
      });
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

  if (mainSearch) {
    mainSearch.addEventListener('input', function () {
      doLiveSearch(mainSearch.value);
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
      const typeSelect = document.getElementById('type-select');
      if (typeSelect) typeSelect.value = type;

      typeChips.forEach(function (c) {
        c.classList.remove('active', 'active-green');
        c.setAttribute('aria-pressed', 'false');
      });
      chip.classList.add(type === 'State' ? 'active-green' : 'active');
      chip.setAttribute('aria-pressed', 'true');

      let visible = 0;
      schemeCards.forEach(function (card) {
        const ct = (card.dataset.schemeType || '').toLowerCase();
        const match = !type || ct === type.toLowerCase();
        card.style.display = match ? '' : 'none';
        if (match) visible++;
      });

      updateResultCount(visible);
      const resultCount = document.getElementById('sp-result-count');
      if (resultCount) {
        resultCount.dataset.activeType = type;
        const typeLabel = type ? ` ${type} schemes` : ' schemes';
        resultCount.querySelector('strong').nextSibling.textContent = typeLabel;
      }
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
    const validSchemeId = positiveSchemeId(schemeId);
    const card = validSchemeId
      ? Array.from(document.querySelectorAll('.sp-scheme-card[data-scheme-id]'))
        .find((candidate) => candidate.dataset.schemeId === validSchemeId)
      : null;
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

    const badgesContainer = modal.querySelector('#sp-details-badges');
    badgesContainer.replaceChildren();
    [type, state].concat(category && category !== 'all' ? [category] : []).forEach(function (value) {
      const badge = document.createElement('span');
      badge.className = 'sp-details-badge';
      badge.textContent = value;
      badgesContainer.appendChild(badge);
    });

    const body = modal.querySelector('#sp-details-body');
    body.replaceChildren();

    const description = document.createElement('p');
    description.textContent = desc;
    body.appendChild(description);

    const department = document.createElement('p');
    const departmentLabel = document.createElement('strong');
    departmentLabel.textContent = 'Department:';
    department.appendChild(departmentLabel);
    department.appendChild(document.createTextNode(' ' + dept));
    body.appendChild(department);

    if (minAge || maxAge) {
      const eligibility = document.createElement('div');
      const eligibilityLabel = document.createElement('strong');
      eligibilityLabel.textContent = 'Eligibility';
      eligibility.appendChild(eligibilityLabel);

      const eligibilityList = document.createElement('ul');
      const age = document.createElement('li');
      const ageLabel = document.createElement('strong');
      ageLabel.textContent = 'Age:';
      age.appendChild(ageLabel);
      age.appendChild(document.createTextNode(' ' + (minAge || '-') + ' - ' + (maxAge || '-') + ' years'));
      eligibilityList.appendChild(age);
      eligibility.appendChild(eligibilityList);
      body.appendChild(eligibility);
    }

    if (incomeLimit) {
      let eligibility = body.querySelector('div');
      if (!eligibility) {
        eligibility = document.createElement('div');
        const eligibilityLabel = document.createElement('strong');
        eligibilityLabel.textContent = 'Eligibility';
        eligibility.appendChild(eligibilityLabel);
        eligibility.appendChild(document.createElement('ul'));
        body.appendChild(eligibility);
      }

      const income = document.createElement('li');
      const incomeLabel = document.createElement('strong');
      incomeLabel.textContent = 'Income:';
      income.appendChild(incomeLabel);
      income.appendChild(document.createTextNode(' <= Rs ' + incomeLimit + ' / year'));
      eligibility.querySelector('ul').appendChild(income);
    }

    let officialUrl = null;
    if (officialWebsite) {
      try {
        const parsedUrl = new URL(officialWebsite, window.location.origin);
        if (parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:') {
          officialUrl = parsedUrl.href;
        }
      } catch (error) {
        officialUrl = null;
      }
    }
    if (officialUrl) {
      const website = document.createElement('p');
      const websiteLink = document.createElement('a');
      websiteLink.href = officialUrl;
      websiteLink.target = '_blank';
      websiteLink.rel = 'noopener noreferrer';
      websiteLink.textContent = 'Visit official website';
      website.appendChild(websiteLink);
      body.appendChild(website);
    }

    const applyUrl = defaultApplicationUrl(validSchemeId);
    const applyLink = modal.querySelector('#sp-details-apply');
    applyLink.setAttribute('href', applyUrl);
    applyLink.onclick = function (e) {
      e.preventDefault();
      window.handleApplyNow(validSchemeId, applyUrl);
    };

    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
  };

})();
