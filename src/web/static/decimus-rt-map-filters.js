/* D746: filter the actual, already rendered map cells; no hidden data requests. */
(() => {
  function init() {
  document.querySelectorAll('[data-map-filters]').forEach((root) => {
    if (root.dataset.filterBound) return;
    root.dataset.filterBound = '1';
    const controls = root.querySelector('.rt-map-filters');
    if (!controls) return;
    const rows = Array.from(root.querySelectorAll('[data-map-row]'));
    controls.hidden = false;
    controls.addEventListener('click', (event) => {
      const button = event.target.closest('[data-map-filter]');
      if (!button || !controls.contains(button)) return;
      const key = button.dataset.mapFilter;
      if (!['all', 'low', 'stale', 'missing'].includes(key)) return;
      controls.querySelectorAll('[data-map-filter]').forEach((item) => {
        item.setAttribute('aria-pressed', String(item === button));
      });
      rows.forEach((row) => {
        row.hidden = key !== 'all' && row.getAttribute(`data-map-${key}`) !== 'true';
      });
    });
  });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  document.addEventListener('decimus:ratings', init);
  document.addEventListener('decimus:navigation', init);
})();
