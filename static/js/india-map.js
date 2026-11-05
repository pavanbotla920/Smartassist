(function () {
  'use strict';
  const body = document.body;
  const $ = (id) => document.getElementById(id);
  const i18n = {
    unavailable: body.dataset.mapUnavailable || 'Data unavailable',
    loadError: body.dataset.mapLoadError || 'The map could not be loaded. Please refresh and try again.',
    schemes: body.dataset.mapSchemesLabel || 'schemes',
    central: body.dataset.mapCentralLabel || 'central',
    state: body.dataset.mapStateLabel || 'state',
    selected: body.dataset.mapSelectedLabel || 'State selected',
    viewing: body.dataset.mapViewingLabel || 'Viewing welfare schemes for'
  };
  const format = (n) => Number(n || 0).toLocaleString('en-IN');
  const els = { loading: $('map-loading'), error: $('map-error'), tooltip: $('state-tooltip'), status: $('panel-status'), name: $('selected-state-name'), subtitle: $('selected-state-subtitle'), total: $('scheme-count'), central: $('central-scheme-count'), state: $('state-scheme-count'), link: $('view-schemes'), announcement: $('map-announcement') };
  const metricsCache = {};
  let selectedLayer = null;
  const defaultStyle = { color:'#fff', weight:1.25, opacity:1, fillColor:'#cfe8d9', fillOpacity:.92 };
  const hoverStyle = { color:'#fff', weight:2, opacity:1, fillColor:'#e1b554', fillOpacity:.95 };
  const selectedStyle = { color:'#fff', weight:2.5, opacity:1, fillColor:'#174c3b', fillOpacity:.95 };
  function stateName(feature) { return String(feature.properties?.name || feature.properties?.ST_NM || feature.properties?.state || feature.properties?.STATE_NAME || '').trim(); }
  function metrics(name) {
    if (metricsCache[name]) return Promise.resolve(metricsCache[name]);
    const url = body.dataset.stateApiUrl.replace('__state__', encodeURIComponent(name));
    return fetch(url).then((r) => { if (!r.ok) throw new Error('state metrics'); return r.json(); }).then((items) => {
      const value = { total:items.length, central:items.filter((x) => String(x.scheme_type || '').toLowerCase() === 'central').length };
      value.state = value.total - value.central; metricsCache[name] = value; return value;
    });
  }
  function setInsight(name, value) {
    els.name.textContent = name;
    els.subtitle.textContent = i18n.viewing.replace('{state}', name);
    els.total.textContent = format(value.total); els.central.textContent = format(value.central); els.state.textContent = format(value.state);
    els.status.textContent = i18n.selected; els.link.href = body.dataset.stateDashboardUrl.replace('__state__', encodeURIComponent(name)); els.link.classList.remove('is-disabled'); els.link.removeAttribute('aria-disabled');
    els.announcement.textContent = `${name}: ${format(value.total)} schemes, ${format(value.central)} central and ${format(value.state)} state schemes.`;
  }
  function positionTooltip(event) {
    const frame = document.querySelector('.map-frame');
    const point = event.containerPoint;
    if (!frame || !point) return;
    const gap = 12;
    const maxLeft = frame.clientWidth - els.tooltip.offsetWidth - 16;
    const maxTop = frame.clientHeight - els.tooltip.offsetHeight - 16;
    els.tooltip.style.left = `${Math.max(8, Math.min(point.x + gap, maxLeft))}px`;
    els.tooltip.style.top = `${Math.max(8, Math.min(point.y + gap, maxTop))}px`;
  }
  function tooltip(name, value, event) {
    els.tooltip.replaceChildren();

    const title = document.createElement('strong');
    title.textContent = name;
    els.tooltip.appendChild(title);

    const total = document.createElement('span');
    total.textContent = `${format(value.total)} ${i18n.schemes}`;
    els.tooltip.appendChild(total);

    const breakdown = document.createElement('span');
    breakdown.textContent = `${format(value.central)} ${i18n.central} · ${format(value.state)} ${i18n.state}`;
    els.tooltip.appendChild(breakdown);

    els.tooltip.classList.add('visible');
    positionTooltip(event);
  }
  function loadOverview() {
    return fetch(body.dataset.overviewUrl).then((r) => { if (!r.ok) throw new Error('overview'); return r.json(); }).then((data) => {
      $('active-state-count').textContent = format(data.active_states); $('overview-total').textContent = format(data.total_schemes); $('overview-central').textContent = format(data.central_schemes); $('overview-state').textContent = format(data.state_schemes);
    });
  }
  function init() {
    const map = L.map('india-map', { center:[22,79], zoom:5, minZoom:4, maxZoom:7, scrollWheelZoom:false, zoomControl:true });
    fetch(body.dataset.geojsonUrl).then((r) => { if (!r.ok) throw new Error('geojson'); return r.json(); }).then((data) => {
      if (!data.features?.length) throw new Error('empty geojson');
      const layer = L.geoJSON(data, { style:defaultStyle, onEachFeature:(feature, stateLayer) => {
        const name = stateName(feature) || 'Unknown state'; stateLayer.options.title = name;
        stateLayer.on({
          mouseover: (event) => { if (selectedLayer !== stateLayer) stateLayer.setStyle(hoverStyle); metrics(name).then((value) => tooltip(name, value, event)).catch(() => tooltip(name, { total:0, central:0, state:0 }, event)); },
          mousemove: (event) => { positionTooltip(event); },
          mouseout: () => { if (selectedLayer !== stateLayer) stateLayer.setStyle(defaultStyle); els.tooltip.classList.remove('visible'); },
          click: () => { els.tooltip.classList.remove('visible'); if (selectedLayer && selectedLayer !== stateLayer) selectedLayer.setStyle(defaultStyle); selectedLayer = stateLayer; stateLayer.setStyle(selectedStyle); metrics(name).then((value) => setInsight(name, value)).catch(() => { els.status.textContent = i18n.unavailable; }); }
        });
        stateLayer.getElement?.()?.setAttribute('tabindex','0');
      }}).addTo(map);
      layer.eachLayer((stateLayer) => {
        const element = stateLayer.getElement?.();
        if (!element) return;
        const name = stateLayer.options.title || 'state';
        element.setAttribute('tabindex', '0');
        element.setAttribute('role', 'button');
        element.setAttribute('aria-label', `Select ${name}`);
        element.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            stateLayer.fire('click');
          }
        });
      });
      map.fitBounds(layer.getBounds(), { padding:[18,18] }); els.loading.hidden = true; setTimeout(() => map.invalidateSize(), 180);
    }).catch(() => { els.loading.hidden = true; els.error.hidden = false; els.error.textContent = i18n.loadError; });
    loadOverview().catch(() => { $('active-state-count').textContent = '—'; $('overview-total').textContent = '—'; $('overview-central').textContent = '—'; $('overview-state').textContent = '—'; });
  }
  document.addEventListener('DOMContentLoaded', init);
}());
