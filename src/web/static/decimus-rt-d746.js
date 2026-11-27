/* Native details retain a no-script disclosure; JS supplies modal keyboard behaviour. */
(function () {
  'use strict';
  function init() {
    document.querySelectorAll('[data-overview-sort]').forEach(function (box) {
      if (box.dataset.sortBound) return;
      box.dataset.sortBound = '1';
      var select = box.querySelector('[data-overview-order]');
      function sort() {
        var body = box.querySelector('tbody');
        Array.from(body.rows).sort(function (a, b) {
          var av = a.getAttribute('data-' + select.value);
          var bv = b.getAttribute('data-' + select.value);
          if (av === '') return bv === '' ? 0 : 1;
          if (bv === '') return -1;
          return Number(bv) - Number(av);
        }).forEach(function (row) { body.appendChild(row); });
      }
      select.addEventListener('change', sort);
      sort();
    });
    document.querySelectorAll('[data-violations-dialog]').forEach(function (details) {
      if (details.dataset.dialogBound) return;
      details.dataset.dialogBound = '1';
      var panel = details.querySelector('.rt-violations__panel');
      // Кнопки «Нарушения» больше нет: открывает плитка, фокус после закрытия возвращается ей.
      var summary = details.querySelector('summary');
      function opener() { return document.querySelector('[data-open-violations]') || summary; }
      function close() { details.open = false; opener().focus(); }
      details.addEventListener('toggle', function () {
        summary.setAttribute('aria-expanded', String(details.open));
        if (details.open) panel.querySelector('[data-close-violations]').focus();
      });
      details.querySelector('[data-close-violations]').addEventListener('click', close);
      var exporter = details.querySelector('[data-export-violations]');
      exporter.addEventListener('click', function () {
        var table = panel.querySelector('table');
        if (!table) return;
        function cell(value) {
          value = value.trim();
          if (/^[=+@-]/.test(value)) value = "'" + value;
          return '"' + value.replace(/"/g, '""') + '"';
        }
        var csv = Array.from(table.rows).map(function (row) {
          return Array.from(row.cells).map(function (td) { return cell(td.innerText); }).join(',');
        }).join('\r\n');
        var url = URL.createObjectURL(new Blob(['\uFEFF' + csv], {type:'text/csv;charset=utf-8'}));
        var link = document.createElement('a');
        link.href = url; link.download = 'ratings-violations.csv'; link.click();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      });
      if (new URLSearchParams(window.location.search).get('show_violations') === '1') details.open = true;
      details.addEventListener('click', function (event) { if (event.target === details) close(); });
      details.addEventListener('keydown', function (event) {
        if (!details.open) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        if (event.key !== 'Tab') return;
        var all = Array.from(panel.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]'));
        if (!all.length) return;
        var first = all[0], last = all[all.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
    });
  }
  if (!document.documentElement.dataset.rtVisualClicks) {
    document.documentElement.dataset.rtVisualClicks = '1';
    document.addEventListener('click', function (event) {
      var opener = event.target.closest('[data-open-violations]');
      if (!opener) return;
      var details = document.querySelector('[data-violations-dialog]');
      if (details) {
        event.preventDefault();
        details.open = true;
        details.querySelector('[data-close-violations]').focus();
      }
    });
    // A KPI outside <details> can retain focus before the native toggle event.
    // Escape belongs to the open modal even during that opening interval.
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      var details = document.querySelector('[data-violations-dialog][open]');
      if (!details) return;
      event.preventDefault();
      event.stopPropagation();
      details.open = false;
      (document.querySelector('[data-open-violations]') || details.querySelector('summary')).focus();
    }, true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  document.addEventListener('decimus:navigation', init);
  document.addEventListener('decimus:ratings', init);
})();
