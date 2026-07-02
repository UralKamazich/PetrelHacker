const metricOptions = [
  ['Thickness', 'thickness'],
  ['Net thickness', 'net_thickness'],
  ['NTG avg', 'ntg_avg'],
  ['NTG median', 'ntg_median'],
  ['PORO avg', 'poro_avg'],
  ['PORO median', 'poro_median'],
  ['PERM arithmetic avg', 'perm_avg_arith'],
  ['PERM geometric avg', 'perm_avg_geom'],
  ['PERM median', 'perm_median'],
  ['KH', 'kh'],
  ['PHIH', 'phih'],
  ['Additional: avg', 'avg'],
  ['Additional: arithmetic mean', 'mean_arith'],
  ['Additional: geometric mean', 'geom'],
  ['Additional: median', 'median'],
  ['Additional: min', 'min'],
  ['Additional: max', 'max'],
  ['Additional: integral', 'integral'],
  ['Additional: min*', 'min_star'],
  ['Additional: max*', 'max_star'],
  ['Additional: std', 'std'],
  ['Additional: delta', 'delta']
];

const metadataColumns = new Set([
  'Well', 'Port', 'X', 'Y', 'TVDSS_PORT', 'Datum_Z', 'Depth_KB_PORT',
  'I', 'J', 'K', 'IsActive', 'TVDSS_top', 'TVDSS_base', 'TVDSS_center',
  'TVD_top', 'TVD_base', 'TVD_center', 'Depth_KB_top', 'Depth_KB_base',
  'Depth_KB_center', 'Rel_TVD_top', 'Rel_TVD_base', 'Rel_TVD_center',
  'CellHeight', 'CellSizeI', 'CellSizeJ', 'CellAreaXY', 'WellKey',
  'PortKey', 'XKey', 'YKey'
]);

const state = {
  models: [{ label: 'M1', path: '', depthOffset: 0 }, { label: 'M2', path: '', depthOffset: 0 }, { label: 'M3', path: '', depthOffset: 0 }],
  loadedModels: [],
  sleeves: null,
  selectedWells: [],
  tableColumns: [],
  curveRows: []
};

const $ = id => document.getElementById(id);

function init() {
  renderModels();
  renderMetricKeys();
  renderCurveControls();
  restoreState();
  bindNavigation();
  bindActions();
  window.petrel.onBackendEvent(handleBackendEvent);
}

function bindNavigation() {
  document.querySelectorAll('.nav-item').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
      document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
      button.classList.add('active');
      $(`view-${button.dataset.view}`).classList.add('active');
    });
  });
}

function bindActions() {
  $('load-models').addEventListener('click', loadModels);
  $('load-sleeves').addEventListener('click', loadSleeves);
  $('run-extraction').addEventListener('click', runExtraction);
  $('browse-sleeves').addEventListener('click', async () => setPath('sleeves-path', await pickTable()));
  $('browse-output').addEventListener('click', browseExtractionOutput);
  $('well-dropdown-button').addEventListener('click', toggleWellDropdown);
  $('select-all-wells').addEventListener('click', () => setAllWells(true));
  $('clear-wells').addEventListener('click', () => setAllWells(false));
  $('well-search').addEventListener('input', renderWells);
  $('select-all-properties').addEventListener('click', () => setAllProperties(true));
  $('clear-properties').addEventListener('click', () => setAllProperties(false));
  $('browse-metrics-extracted').addEventListener('click', async () => setPath('metrics-extracted', await pickTable()));
  $('browse-metrics-intervals').addEventListener('click', browseMetricsIntervals);
  $('browse-metrics-output').addEventListener('click', browseMetricsOutput);
  $('load-metrics-table').addEventListener('click', loadMetricsTable);
  $('run-metrics').addEventListener('click', runMetrics);
  $('browse-curve-path').addEventListener('click', async () => setPath('curve-path', await pickTable()));
  $('load-curve-table').addEventListener('click', loadCurveTable);
  $('draw-curves').addEventListener('click', drawCurves);
  $('clear-log').addEventListener('click', () => $('log-view').textContent = '');
  ['curve-well', 'curve-port'].forEach(id => $(id).addEventListener('change', drawCurves));
  document.addEventListener('click', event => {
    const dropdown = document.querySelector('.well-dropdown');
    if (dropdown && !dropdown.contains(event.target)) closeWellDropdown();
  });
}

function renderModels() {
  const root = $('model-stack');
  root.innerHTML = '';
  state.models.forEach((model, index) => {
    const card = document.createElement('div');
    card.className = 'model-card';
    card.innerHTML = `
      <div class="model-badge">${model.label}</div>
      <label class="field"><span>Model folder</span><input type="text" value="${escapeHtml(model.path)}" data-model-path="${index}" placeholder="Select folder with .epc or .bin model"></label>
      <label class="field"><span>Depth shift, m</span><input type="number" step="0.1" value="${model.depthOffset}" data-model-offset="${index}"></label>
      <button class="icon-button" data-model-browse="${index}">...</button>
    `;
    root.appendChild(card);
  });
  root.querySelectorAll('[data-model-path]').forEach(input => {
    input.addEventListener('input', () => {
      state.models[Number(input.dataset.modelPath)].path = input.value;
      saveState();
    });
  });
  root.querySelectorAll('[data-model-offset]').forEach(input => {
    input.addEventListener('input', () => {
      state.models[Number(input.dataset.modelOffset)].depthOffset = Number(input.value || 0);
      saveState();
    });
  });
  root.querySelectorAll('[data-model-browse]').forEach(button => {
    button.addEventListener('click', async () => {
      const index = Number(button.dataset.modelBrowse);
      const selected = await window.petrel.openModel();
      if (!selected) return;
      state.models[index].path = selected;
      renderModels();
      saveState();
    });
  });
}

async function loadModels() {
  setBusy('Loading models', 'Reading grids and property cubes');
  try {
    const result = await window.petrel.run('load-models', { models: requestModels() });
    state.loadedModels = result.models || [];
    state.loadedModels.forEach(loaded => {
      const model = state.models.find(item => item.label === loaded.label);
      if (model && loaded.path) model.path = loaded.path;
    });
    renderModels();
    renderProperties();
    saveState();
    setReady(`Loaded ${state.loadedModels.length} model(s)`);
  } catch (error) {
    fail(error);
  }
}

async function loadSleeves() {
  const path = $('sleeves-path').value.trim();
  if (!path) return fail(new Error('Select sleeves table first.'));
  setBusy('Loading sleeves', 'Reading frac-list and wells');
  try {
    const result = await window.petrel.run('preview-sleeves', { path });
    state.sleeves = result;
    state.selectedWells = (result.wells || []).map(well => well.name);
    renderMapping(result);
    renderWells();
    if (!$('output-path').value.trim()) {
      const suggested = await window.petrel.run('suggest-output', { sleevesPath: path });
      $('output-path').value = basename(suggested.outputPath || '');
    }
    applyMetricsDefaultsFromSleeves(path);
    saveState();
    setReady(`Sleeves: ${result.rows} rows`);
  } catch (error) {
    fail(error);
  }
}

function renderMapping(result) {
  const root = $('mapping-grid');
  root.innerHTML = '';
  ['Well', 'Port', 'X', 'Y', 'TVDSS_PORT'].forEach(target => {
    const field = document.createElement('label');
    field.className = 'field';
    const options = [''].concat(result.columns || []).map(column => {
      const selected = result.columnMapping && result.columnMapping[target] === column ? 'selected' : '';
      return `<option value="${escapeHtml(column)}" ${selected}>${escapeHtml(column || '-')}</option>`;
    }).join('');
    field.innerHTML = `<span>${target}</span><select data-map-target="${target}">${options}</select>`;
    root.appendChild(field);
  });
}

function currentColumnMapping() {
  const mapping = {};
  document.querySelectorAll('[data-map-target]').forEach(select => {
    if (select.value) mapping[select.dataset.mapTarget] = select.value;
  });
  return mapping;
}

function renderWells() {
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  $('well-summary').textContent = wellSummaryText(wells);
  const root = $('well-list');
  root.innerHTML = '';
  const query = $('well-search').value.trim().toLowerCase();
  wells
    .filter(well => !query || well.name.toLowerCase().indexOf(query) >= 0)
    .forEach(well => {
    const row = document.createElement('label');
    row.className = 'well-item';
    const checked = state.selectedWells.indexOf(well.name) >= 0 ? 'checked' : '';
    row.innerHTML = `<input type="checkbox" ${checked} data-well="${escapeHtml(well.name)}"><span>${escapeHtml(well.name)}</span><span class="muted">${well.count}</span>`;
    root.appendChild(row);
  });
  root.querySelectorAll('[data-well]').forEach(input => {
    input.addEventListener('change', () => {
      const name = input.dataset.well;
      if (input.checked && state.selectedWells.indexOf(name) < 0) state.selectedWells.push(name);
      if (!input.checked) state.selectedWells = state.selectedWells.filter(value => value !== name);
      renderWells();
      saveState();
    });
  });
}

function setAllWells(checked) {
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  state.selectedWells = checked ? wells.map(well => well.name) : [];
  renderWells();
  saveState();
}

function wellSummaryText(wells) {
  if (!wells.length) return 'No sleeves loaded';
  if (!state.selectedWells.length) return 'No wells selected';
  if (state.selectedWells.length === wells.length) return `All wells (${wells.length})`;
  if (state.selectedWells.length <= 2) return state.selectedWells.join(', ');
  return `${state.selectedWells.length} of ${wells.length} wells`;
}

function toggleWellDropdown() {
  const panel = $('well-dropdown-panel');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) {
    $('well-search').focus();
  }
}

function closeWellDropdown() {
  $('well-dropdown-panel').classList.remove('open');
}

function renderProperties() {
  const root = $('property-table');
  root.innerHTML = '';
  state.loadedModels.forEach(model => {
    (model.properties || []).forEach(prop => {
      const row = document.createElement('label');
      row.className = 'property-row';
      const checked = shouldAutoSelect(prop.title) ? 'checked' : '';
      row.innerHTML = `
        <input type="checkbox" ${checked} data-property="${escapeHtml(prop.uuid)}" data-model="${escapeHtml(model.label)}" data-property-title="${escapeHtml(prop.title)}">
        <strong>${escapeHtml(model.label)}</strong>
        <span>${escapeHtml(prop.title)}</span>
        <span class="muted">${escapeHtml(prop.property_kind || prop.property_type || '')}</span>
      `;
      root.appendChild(row);
    });
  });
  root.querySelectorAll('[data-property]').forEach(input => {
    input.addEventListener('change', () => {
      if (state.tableColumns.length) renderMetricsProperties(state.tableColumns);
      saveState();
    });
  });
}

function setAllProperties(checked) {
  document.querySelectorAll('[data-property]').forEach(input => input.checked = checked);
  if (state.tableColumns.length) renderMetricsProperties(state.tableColumns);
  saveState();
}

function selectedModelsWithProperties() {
  const byLabel = {};
  document.querySelectorAll('[data-property]:checked').forEach(input => {
    if (!byLabel[input.dataset.model]) byLabel[input.dataset.model] = [];
    byLabel[input.dataset.model].push(input.dataset.property);
  });
  return requestModels().map(model => Object.assign({}, model, {
    selectedPropertyUuids: byLabel[model.label] || []
  }));
}

async function runExtraction() {
  setBusy('Extracting', 'Building output table');
  try {
    const result = await window.petrel.run('extract', {
      models: selectedModelsWithProperties(),
      sleevesPath: $('sleeves-path').value.trim(),
      outputPath: extractionOutputPath(),
      selectedWells: state.selectedWells,
      columnMapping: currentColumnMapping(),
      skipInactive: $('skip-inactive').checked,
      writeDiagnostics: $('write-diagnostics').checked,
      parallelWorkers: Number($('parallel-workers').value || 1)
    });
    $('metrics-extracted').value = result.outputPath || '';
    $('curve-path').value = result.outputPath || '';
    applyMetricsDefaultsFromSleeves($('sleeves-path').value.trim());
    setProgress('extraction-progress', 100);
    setReady('Extraction complete');
    saveState();
  } catch (error) {
    fail(error);
  }
}

async function loadMetricsTable() {
  const path = $('metrics-extracted').value.trim();
  if (!path) return fail(new Error('Select extracted table first.'));
  setBusy('Reading table', 'Loading headers');
  try {
    const result = await window.petrel.run('table-info', { path });
    state.tableColumns = result.columns || [];
    fillSelect('metrics-ntg', state.tableColumns, guessColumn(state.tableColumns, ['NTG']));
    fillSelect('metrics-poro', state.tableColumns, guessColumn(state.tableColumns, ['PORO']));
    fillSelect('metrics-perm', state.tableColumns, guessColumn(state.tableColumns, ['PERM']));
    fillSelect('metrics-lithology', state.tableColumns, guessColumn(state.tableColumns, ['LITH', 'FACIES']));
    renderMetricsProperties(state.tableColumns);
    setReady(`Headers: ${state.tableColumns.length}`);
  } catch (error) {
    fail(error);
  }
}

function renderMetricsProperties(columns) {
  const root = $('metrics-properties');
  root.innerHTML = '';
  metricAdditionalColumns(columns).forEach(column => {
    const row = document.createElement('label');
    row.className = 'check-item';
    row.innerHTML = `<input type="checkbox" data-metrics-property="${escapeHtml(column)}"><span>${escapeHtml(column)}</span><span></span>`;
    root.appendChild(row);
  });
}

function metricAdditionalColumns(columns) {
  const refs = selectedPropertyRefs();
  if (!refs.length) return [];
  return columns.filter(column => isPropertyColumn(column) && matchesSelectedProperty(column, refs));
}

function selectedPropertyRefs() {
  return Array.prototype.slice.call(document.querySelectorAll('[data-property]:checked')).map(input => ({
    model: input.dataset.model || '',
    title: input.dataset.propertyTitle || ''
  })).filter(ref => ref.title);
}

function matchesSelectedProperty(column, refs) {
  const parsed = splitModelPropertyColumn(column);
  const normalizedTitle = normalizeName(parsed.title);
  return refs.some(ref => {
    if (normalizeName(ref.title) !== normalizedTitle) return false;
    return !parsed.model || parsed.model === ref.model;
  });
}

function splitModelPropertyColumn(column) {
  const value = String(column);
  const match = /^(M\d+)_(.+)$/.exec(value);
  return match ? { model: match[1], title: match[2] } : { model: '', title: value };
}

function renderMetricKeys() {
  const root = $('metric-keys');
  root.innerHTML = '';
  metricOptions.forEach(([label, key]) => {
    const row = document.createElement('label');
    row.className = 'check-item';
    row.innerHTML = `<input type="checkbox" checked data-metric-key="${key}"><span>${escapeHtml(label)}</span><span></span>`;
    root.appendChild(row);
  });
}

async function runMetrics() {
  setBusy('Calculating metrics', 'Processing intervals');
  try {
    const result = await window.petrel.run('metrics', {
      extractedPath: $('metrics-extracted').value.trim(),
      intervalsPath: $('metrics-intervals').value.trim(),
      outputPath: metricsOutputPath(),
      ntgColumn: valueOrNull('metrics-ntg'),
      poroColumn: valueOrNull('metrics-poro'),
      permColumn: valueOrNull('metrics-perm'),
      lithologyColumn: valueOrNull('metrics-lithology'),
      reservoirValues: splitCsv($('reservoir-values').value),
      propertyColumns: checkedValues('metrics-property'),
      metricKeys: checkedValues('metric-key')
    });
    setProgress('metrics-progress', 100);
    setReady(`Metrics rows: ${result.rowsWritten || 0}`);
  } catch (error) {
    fail(error);
  }
}

async function loadCurveTable() {
  const path = $('curve-path').value.trim();
  if (!path) return fail(new Error('Select extracted table first.'));
  setBusy('Reading curves', 'Loading table metadata');
  try {
    const result = await window.petrel.run('table-info', { path });
    state.tableColumns = result.columns || [];
    const wells = result.wells || [];
    const ports = result.ports || [];
    fillSelect('curve-well', wells, wells[0]);
    fillSelect('curve-port', ports, ports[0]);
    $('curve-depth-mode').value = 'common';
    renderCurveControls(true);
    await autoFitAndDrawCurves();
    setReady(`Curve table: ${result.rows} rows`);
  } catch (error) {
    fail(error);
  }
}

function renderCurveControls(autoSelect) {
  const root = $('curve-controls');
  root.innerHTML = '';
  const columns = curveChannelColumns();
  for (let index = 1; index <= 4; index += 1) {
    const control = document.createElement('div');
    control.className = 'curve-control';
    control.innerHTML = `
      <label class="field"><span>Channel ${index}</span><select id="curve-channel-${index}"></select></label>
      <div class="curve-control-grid">
        <label class="field"><span>Min</span><input id="curve-min-${index}" type="number" step="0.01"></label>
        <label class="field"><span>Max</span><input id="curve-max-${index}" type="number" step="0.01"></label>
        <label class="field"><span>Shift m</span><input id="curve-shift-${index}" type="number" step="0.1" value="0"></label>
      </div>
    `;
    root.appendChild(control);
    fillSelect(`curve-channel-${index}`, columns, autoSelect ? columns[index - 1] : undefined);
  }
}

function curveChannelColumns() {
  return state.tableColumns.filter(isPropertyColumn);
}

function isPropertyColumn(column) {
  const parsed = splitModelPropertyColumn(column);
  return !metadataColumns.has(String(column)) && !metadataColumns.has(parsed.title) && !isSourceDiagnosticColumn(column);
}

function isSourceDiagnosticColumn(column) {
  return /_(Model|I|J|K|TVD_center|Depth_KB)$/.test(column);
}

async function drawCurves() {
  const path = $('curve-path').value.trim();
  if (!path) return fail(new Error('Select extracted table first.'));
  const columns = selectedCurveColumns();
  setBusy('Drawing curves', 'Loading selected well/port');
  try {
    const result = await loadCurveRows(columns);
    paintCurves(result.depthColumn, result.channelDepthColumns || {}, columns, result.rows || []);
    setReady(`Curve rows: ${state.curveRows.length}`);
  } catch (error) {
    fail(error);
  }
}

async function autoFitAndDrawCurves() {
  const columns = selectedCurveColumns();
  if (!columns.length) {
    plotEmpty('No curve channels');
    return;
  }
  setBusy('Drawing curves', 'Auto-fitting selected well/port');
  const result = await loadCurveRows(columns);
  autoFitCurveRanges(result.depthColumn, result.channelDepthColumns || {}, columns, result.rows || []);
  paintCurves(result.depthColumn, result.channelDepthColumns || {}, columns, result.rows || []);
}

async function loadCurveRows(columns) {
  const result = await window.petrel.run('curve-data', {
    path: $('curve-path').value.trim(),
    well: $('curve-well').value,
    port: $('curve-port').value,
    depthMode: $('curve-depth-mode').value,
    columns
  });
  state.curveRows = result.rows || [];
  return result;
}

function selectedCurveColumns() {
  const columns = [];
  for (let index = 1; index <= 4; index += 1) {
    const select = $(`curve-channel-${index}`);
    if (select && select.value) columns.push(select.value);
  }
  return columns;
}

function autoFitCurveRanges(defaultDepthColumn, channelDepthColumns, columns, rows) {
  const intervals = columns.map(column => {
    const depthColumn = channelDepthColumns[column] || defaultDepthColumn;
    const depths = rows.map(row => {
      const depth = numericCell(row[depthColumn]);
      const value = numericCell(row[column]);
      return Number.isFinite(depth) && Number.isFinite(value) ? depth : NaN;
    }).filter(Number.isFinite);
    if (!depths.length) return null;
    const min = Math.min.apply(null, depths);
    const max = Math.max.apply(null, depths);
    return { min, max, span: max - min };
  }).filter(Boolean);
  if (intervals.length) {
    const shortest = intervals.reduce((best, item) => item.span < best.span ? item : best, intervals[0]);
    $('curve-depth-min').value = formatInputNumber(shortest.min - 50, 1);
    $('curve-depth-max').value = formatInputNumber(shortest.max + 50, 1);
  }
  columns.forEach((column, index) => {
    const values = rows.map(row => numericCell(row[column])).filter(Number.isFinite);
    if (!values.length) return;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = max - min;
    const pad = span > 0 ? span * 0.1 : Math.max(Math.abs(max) * 0.1, 1);
    $(`curve-min-${index + 1}`).value = formatInputNumber(min, 4);
    $(`curve-max-${index + 1}`).value = formatInputNumber(max + pad, 4);
  });
}

function paintCurves(defaultDepthColumn, channelDepthColumns, columns, rows) {
  const depths = [];
  columns.forEach((column, index) => {
    const depthColumn = channelDepthColumns[column] || defaultDepthColumn;
    const shift = Number($(`curve-shift-${index + 1}`).value || 0);
    rows.forEach(row => {
      const depth = numericCell(row[depthColumn]);
      const value = numericCell(row[column]);
      if (Number.isFinite(depth) && Number.isFinite(value)) depths.push(depth + shift);
    });
  });
  if (!depths.length) {
    plotEmpty('No curve data');
    return;
  }
  let depthMin = numericInput('curve-depth-min');
  let depthMax = numericInput('curve-depth-max');
  if (!Number.isFinite(depthMin)) depthMin = Math.min.apply(null, depths);
  if (!Number.isFinite(depthMax)) depthMax = Math.max.apply(null, depths);
  if (depthMax === depthMin) depthMax = depthMin + 1;
  const colors = ['#2563eb', '#16a34a', '#9333ea', '#f97316'];
  const traces = [];
  const layout = {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    margin: { l: 72, r: 28, t: 84, b: 74 },
    hovermode: 'closest',
    legend: { orientation: 'h', x: 0, y: 1.18, font: { size: 11 } },
    annotations: [],
    yaxis: {
      title: 'TVD top',
      range: [depthMax, depthMin],
      domain: [0.1, 0.9],
      gridcolor: '#e3e8ef',
      zeroline: false,
      titlefont: { size: 12 },
      tickfont: { size: 11 }
    }
  };
  columns.forEach((column, index) => {
    const values = rows.map(row => numericCell(row[column])).filter(Number.isFinite);
    if (!values.length) return;
    let min = numericInput(`curve-min-${index + 1}`);
    let max = numericInput(`curve-max-${index + 1}`);
    if (!Number.isFinite(min)) min = Math.min.apply(null, values);
    if (!Number.isFinite(max)) max = Math.max.apply(null, values);
    if (max === min) max = min + 1;
    const shift = Number($(`curve-shift-${index + 1}`).value || 0);
    const axisName = index === 0 ? 'x' : `x${index + 1}`;
    const axisKey = index === 0 ? 'xaxis' : `xaxis${index + 1}`;
    const color = colors[index % colors.length];
    const depthColumn = channelDepthColumns[column] || defaultDepthColumn;
    traces.push({
      type: 'scatter',
      mode: 'lines',
      name: shift ? `${column} | shift ${shift} m` : column,
      x: rows.map(row => {
        const depth = numericCell(row[depthColumn]);
        const value = numericCell(row[column]);
        return Number.isFinite(depth) && Number.isFinite(value) ? value : null;
      }),
      y: rows.map(row => {
        const depth = numericCell(row[depthColumn]);
        const value = numericCell(row[column]);
        return Number.isFinite(depth) && Number.isFinite(value) ? depth + shift : null;
      }),
      connectgaps: false,
      xaxis: axisName,
      yaxis: 'y',
      line: { color, width: 2 },
      hovertemplate: `${escapeHtml(column)}<br>Value: %{x}<br>Depth: %{y}<extra></extra>`
    });
    layout[axisKey] = plotlyXAxis(column, min, max, color, index);
    layout.annotations.push(plotlyAxisTitle(column, color, index));
  });
  if (!traces.length) {
    plotEmpty('No curve data');
    return;
  }
  Plotly.react('curve-plot', traces, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: true
  });
}

function plotlyXAxis(title, min, max, color, index) {
  const positions = [0.085, 0.915, 0.955, 0.045];
  const sides = ['bottom', 'top', 'top', 'bottom'];
  const side = sides[index] || 'bottom';
  const axis = {
    tickfont: { color, size: 11 },
    range: [min, max],
    anchor: 'free',
    position: positions[index] || positions[0],
    zeroline: false,
    showgrid: index === 0,
    gridcolor: '#e3e8ef',
    linecolor: color,
    tickcolor: color,
    showline: true,
    ticks: 'outside',
    ticklen: 4,
    automargin: true
  };
  if (index > 0) {
    axis.overlaying = 'x';
  }
  axis.side = side;
  return axis;
}

function plotlyAxisTitle(title, color, index) {
  const yPositions = [0.097, 0.903, 1.012, -0.012];
  return {
    text: escapeHtml(title),
    x: 0.5,
    y: yPositions[index] || 0.096,
    xref: 'paper',
    yref: 'paper',
    showarrow: false,
    xanchor: 'center',
    yanchor: 'middle',
    font: { color, size: 12 }
  };
}

function plotEmpty(text) {
  const element = $('curve-plot');
  if (!window.Plotly || !element) return;
  Plotly.react(element, [], {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    xaxis: { visible: false },
    yaxis: { visible: false },
    annotations: [{ text, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper', showarrow: false, font: { size: 18, color: '#667085' } }]
  }, { displaylogo: false, responsive: true });
}

function handleBackendEvent(message) {
  if (message.event === 'log' && message.message) appendLog(message.message);
  if (message.event === 'progress') {
    if (message.command === 'extract') setProgress('extraction-progress', message.value || 0);
    if (message.command === 'metrics') setProgress('metrics-progress', message.value || 0);
  }
  if (message.event === 'error') appendLog(`ERROR: ${message.message}`);
}

function requestModels() {
  return state.models
    .filter(model => model.path && model.path.trim())
    .map(model => ({ label: model.label, path: model.path.trim(), depthOffset: Number(model.depthOffset || 0) }));
}

function shouldAutoSelect(title) {
  return /(poro|ntg|perm|density|yme|pr_|sta|ta|ti|shmin|shmax)/i.test(title || '');
}

function fillSelect(id, values, selected) {
  const select = $(id);
  if (!select) return;
  select.innerHTML = '<option value=""></option>' + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  if (selected) select.value = selected;
}

function checkedValues(name) {
  return Array.prototype.slice.call(document.querySelectorAll(`[data-${name}]:checked`)).map(input => input.dataset[toCamel(name)]);
}

function toCamel(value) {
  return value.replace(/-([a-z])/g, (_all, char) => char.toUpperCase());
}

function valueOrNull(id) {
  const value = $(id).value.trim();
  return value || null;
}

function splitCsv(value) {
  return value.split(',').map(item => item.trim()).filter(Boolean);
}

function guessColumn(columns, needles) {
  const upperNeedles = needles.map(value => value.toUpperCase());
  return columns.find(column => upperNeedles.some(needle => String(column).toUpperCase().indexOf(needle) >= 0)) || '';
}

async function pickTable() {
  return window.petrel.openFile({ filters: [{ name: 'Tables', extensions: ['xlsx', 'xlsm', 'xls', 'csv'] }, { name: 'All files', extensions: ['*'] }] });
}

async function saveXlsx(name) {
  return window.petrel.saveFile({ defaultPath: name, filters: [{ name: 'Excel / CSV', extensions: ['xlsx', 'csv'] }] });
}

async function browseExtractionOutput() {
  const filename = $('output-path').value.trim() || 'extracted.xlsx';
  const sleevesDir = dirname($('sleeves-path').value.trim());
  const defaultPath = sleevesDir ? joinPath(sleevesDir, filename) : filename;
  const selected = await saveXlsx(defaultPath);
  if (!selected) return;
  $('output-path').value = basename(selected);
  saveState();
}

async function browseMetricsIntervals() {
  const selected = await pickTable();
  if (!selected) return;
  $('metrics-intervals').value = selected;
  if (!$('metrics-output').value.trim()) {
    $('metrics-output').value = metricsDefaultFilename(selected);
  }
  saveState();
}

async function browseMetricsOutput() {
  const filename = $('metrics-output').value.trim() || metricsDefaultFilename(metricsBaseTablePath()) || 'metrics.xlsx';
  const outputDir = dirname(metricsBaseTablePath());
  const defaultPath = outputDir ? joinPath(outputDir, filename) : filename;
  const selected = await saveXlsx(defaultPath);
  if (!selected) return;
  $('metrics-output').value = basename(selected);
  saveState();
}

function setPath(id, value) {
  if (!value) return;
  $(id).value = value;
  saveState();
}

function setBusy(title, subtitle) {
  $('status-title').textContent = title;
  $('status-subtitle').textContent = subtitle;
  appendLog(`${title}: ${subtitle}`);
}

function setReady(subtitle) {
  $('status-title').textContent = 'Ready';
  $('status-subtitle').textContent = subtitle || 'Python backend idle';
}

function fail(error) {
  const message = error && error.message ? error.message : String(error);
  $('status-title').textContent = 'Error';
  $('status-subtitle').textContent = message.split('\n')[0];
  appendLog(`ERROR: ${message}`);
}

function setProgress(id, value) {
  $(id).style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
}

function extractionOutputPath() {
  const filename = $('output-path').value.trim();
  if (!filename) throw new Error('Enter output file name.');
  if (isAbsolutePath(filename)) return filename;
  const sleevesDir = dirname($('sleeves-path').value.trim());
  if (!sleevesDir) throw new Error('Select sleeves table before output file name.');
  return joinPath(sleevesDir, filename);
}

function metricsOutputPath() {
  const filename = $('metrics-output').value.trim();
  if (!filename) throw new Error('Enter metrics output file name.');
  if (isAbsolutePath(filename)) return filename;
  const outputDir = dirname(metricsBaseTablePath());
  if (!outputDir) throw new Error('Select intervals table before metrics output file name.');
  return joinPath(outputDir, filename);
}

function applyMetricsDefaultsFromSleeves(sleevesPath) {
  if (!sleevesPath) return;
  if (!$('metrics-intervals').value.trim()) $('metrics-intervals').value = sleevesPath;
  if (!$('metrics-output').value.trim()) $('metrics-output').value = metricsDefaultFilename(sleevesPath);
}

function metricsBaseTablePath() {
  return $('metrics-intervals').value.trim() || $('sleeves-path').value.trim();
}

function metricsDefaultFilename(tablePath) {
  const name = stripExtension(basename(tablePath || ''));
  return name ? `${name}_metrics.xlsx` : '';
}

function isAbsolutePath(value) {
  return /^[a-zA-Z]:[\\/]/.test(value) || value.startsWith('\\\\') || value.startsWith('/');
}

function normalizeName(value) {
  return String(value || '').trim().toUpperCase();
}

function basename(value) {
  if (!value) return '';
  const normalized = String(value).replace(/[\\/]+$/, '');
  const parts = normalized.split(/[\\/]/);
  return parts[parts.length - 1] || normalized;
}

function stripExtension(value) {
  return String(value || '').replace(/\.[^.\\/]+$/, '');
}

function dirname(value) {
  if (!value) return '';
  const normalized = String(value).replace(/[\\/]+$/, '');
  const index = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'));
  return index > 0 ? normalized.slice(0, index) : '';
}

function joinPath(folder, filename) {
  if (!folder) return filename;
  const separator = folder.indexOf('\\') >= 0 ? '\\' : '/';
  return folder.replace(/[\\/]+$/, '') + separator + filename.replace(/^[\\/]+/, '');
}

function appendLog(message) {
  const log = $('log-view');
  log.textContent += `[${new Date().toLocaleTimeString()}] ${message}\n`;
  log.scrollTop = log.scrollHeight;
}

function saveState() {
  const data = {
    models: state.models,
    sleevesPath: $('sleeves-path').value,
    outputPath: $('output-path').value,
    metricsExtracted: $('metrics-extracted').value,
    metricsIntervals: $('metrics-intervals').value,
    metricsOutput: $('metrics-output').value,
    curvePath: $('curve-path').value
  };
  localStorage.setItem('petrelhacker.state', JSON.stringify(data));
}

function restoreState() {
  try {
    const data = JSON.parse(localStorage.getItem('petrelhacker.state') || '{}');
    if (data.models) state.models = data.models;
    renderModels();
    $('sleeves-path').value = data.sleevesPath || '';
    $('output-path').value = basename(data.outputPath || '');
    $('metrics-extracted').value = data.metricsExtracted || '';
    $('metrics-intervals').value = data.metricsIntervals || '';
    $('metrics-output').value = basename(data.metricsOutput || '');
    $('curve-path').value = data.curvePath || '';
  } catch (error) {
    appendLog(`State restore failed: ${error.message}`);
  }
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatNumber(value) {
  return Number(value).toPrecision(4).replace(/\.?0+$/, '');
}

function formatInputNumber(value, precision) {
  if (!Number.isFinite(value)) return '';
  return Number(value.toFixed(precision)).toString();
}

function numericCell(value) {
  if (value === null || value === undefined || value === '') return NaN;
  const number = Number(value);
  return Number.isFinite(number) ? number : NaN;
}

function numericInput(id) {
  const element = $(id);
  if (!element || element.value === '') return NaN;
  const number = Number(element.value);
  return Number.isFinite(number) ? number : NaN;
}

document.addEventListener('DOMContentLoaded', init);
