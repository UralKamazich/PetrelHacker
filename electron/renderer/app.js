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
  'Well', 'Port', 'X', 'Y', 'TVDSS_PORT', 'MD', 'Datum_Z', 'Depth_KB_PORT',
  'I', 'J', 'K', 'IsActive', 'TVDSS_top', 'TVDSS_base', 'TVDSS_center',
  'TVD_top', 'TVD_base', 'TVD_center', 'Depth_KB_top', 'Depth_KB_base',
  'Depth_KB_center', 'Rel_TVD_top', 'Rel_TVD_base', 'Rel_TVD_center',
  'CellHeight', 'CellSizeI', 'CellSizeJ', 'CellAreaXY', 'WellKey',
  'PortKey', 'XKey', 'YKey'
]);

const sleeveMappingTargets = [
  ['Well', true],
  ['Port', true],
  ['X', false],
  ['Y', false],
  ['TVDSS_PORT', false],
  ['MD', false]
];

const state = {
  models: [{ label: 'M1', path: '', depthOffset: 0 }, { label: 'M2', path: '', depthOffset: 0 }, { label: 'M3', path: '', depthOffset: 0 }],
  loadedModels: [],
  sleeves: null,
  selectedWells: [],
  extractionSelectedProperties: null,
  columnMapping: {},
  hasSavedWellSelection: false,
  tableColumns: [],
  curveRows: [],
  sectionTrajectories: [],
  sectionResult: null,
  sectionRows: [],
  sectionMesh: null,
  sectionWellNameMap: {},
  sectionUseExtractionSelection: false,
  sectionBoundaries: [],
  sectionSavedWells: {},
  sectionBoundaryDrag: null
};

const $ = id => document.getElementById(id);

function init() {
  renderModels();
  renderMetricKeys();
  renderCurveControls();
  renderEmptyMapping();
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
  $('match-wells').addEventListener('click', openWellMatchingModal);
  $('run-extraction').addEventListener('click', runExtraction);
  $('browse-sleeves').addEventListener('click', browseSleeves);
  $('sleeves-path').addEventListener('change', loadSleevesHeaders);
  $('browse-output').addEventListener('click', browseExtractionOutput);
  ['output-path', 'skip-inactive', 'write-diagnostics', 'parallel-workers'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
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
  ['section-property', 'section-well', 'section-step', 'section-max-stations', 'section-skip-inactive'].forEach(id => {
    $(id).addEventListener('change', clearSectionAutoBounds);
  });
  ['section-property', 'section-well', 'section-step', 'section-max-stations', 'section-axis', 'section-skip-inactive'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
  ['section-axis', 'section-depth-min', 'section-depth-max', 'section-value-min', 'section-value-max'].forEach(id => {
    $(id).addEventListener('change', () => {
      if (state.sectionResult) paintSection(state.sectionResult);
    });
  });
  $('load-section-from-extraction').addEventListener('click', loadSectionFromExtraction);
  $('load-section-wells').addEventListener('click', loadSectionWells);
  $('draw-section').addEventListener('click', drawSection);
  $('section-auto-boundaries').addEventListener('click', autoPlaceSectionBoundaries);
  $('section-save-boundaries').addEventListener('click', saveSectionBoundaries);
  $('section-show-boundaries').addEventListener('change', () => {
    if (state.sectionMesh) redrawCurrentSectionMesh();
    saveState();
  });
  $('clear-log').addEventListener('click', () => $('log-view').textContent = '');
  ['curve-well', 'curve-port'].forEach(id => $(id).addEventListener('change', drawCurves));
  window.addEventListener('resize', () => {
    if (state.sectionResult) paintSection(state.sectionResult);
  });
  window.addEventListener('mouseup', stopSectionBoundaryDrag);
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
    renderSectionModels();
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
    const result = await window.petrel.run('preview-sleeves', { path, columnMapping: currentColumnMapping() });
    state.sleeves = result;
    state.selectedWells = selectedWellsForLoadedSleeves(result.wells || []);
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

async function loadSleevesHeaders() {
  const path = $('sleeves-path').value.trim();
  if (!path) return fail(new Error('Select sleeves table first.'));
  setBusy('Loading sleeves', 'Reading frac-list headers');
  try {
    const result = await window.petrel.run('preview-sleeves', { path, headersOnly: true });
    state.sleeves = { ...(state.sleeves || {}), ...result, wells: state.sleeves ? state.sleeves.wells || [] : [] };
    renderMapping(result);
    renderWells();
    if (!$('output-path').value.trim()) {
      const suggested = await window.petrel.run('suggest-output', { sleevesPath: path });
      $('output-path').value = basename(suggested.outputPath || '');
    }
    applyMetricsDefaultsFromSleeves(path);
    saveState();
    setReady(`Sleeves headers: ${result.columns.length} columns`);
  } catch (error) {
    fail(error);
  }
}

async function browseSleeves() {
  const selected = await pickTable();
  if (!selected) return;
  const previous = $('sleeves-path').value.trim();
  $('sleeves-path').value = selected;
  if (selected !== previous) {
    clearSleevesDependentState();
  }
  await loadSleevesHeaders();
}

function clearSleevesDependentState() {
  state.sleeves = null;
  renderEmptyMapping();
  $('well-list').innerHTML = '';
  $('well-summary').textContent = 'No sleeves loaded';
  $('output-path').value = '';
}

function selectedWellsForLoadedSleeves(wells) {
  const available = new Set(wells.map(well => well.name));
  if (state.hasSavedWellSelection) {
    return state.selectedWells.filter(name => available.has(name));
  }
  return wells.map(well => well.name);
}

function renderMapping(result) {
  const root = $('mapping-grid');
  root.innerHTML = '';
  const savedMapping = state.columnMapping || {};
  sleeveMappingTargets.forEach(([target, required]) => {
    const field = document.createElement('label');
    field.className = 'field mapping-field';
    const selectedColumn = savedMapping[target] || (result.columnMapping && result.columnMapping[target]) || '';
    const options = [''].concat(result.columns || []).map(column => {
      const selected = selectedColumn === column ? 'selected' : '';
      return `<option value="${escapeHtml(column)}" ${selected}>${escapeHtml(column || '-')}</option>`;
    }).join('');
    field.innerHTML = `
      <span>${target}${required ? ' *' : ''}</span>
      <select data-map-target="${target}">${options}</select>
    `;
    root.appendChild(field);
  });
  root.querySelectorAll('[data-map-target]').forEach(select => {
    select.addEventListener('change', () => {
      state.columnMapping = currentColumnMapping();
      saveState();
    });
  });
}

function renderEmptyMapping() {
  const root = $('mapping-grid');
  if (!root) return;
  root.innerHTML = '';
  sleeveMappingTargets.forEach(([target, required]) => {
    const field = document.createElement('label');
    field.className = 'field mapping-field';
    field.innerHTML = `
      <span>${target}${required ? ' *' : ''}</span>
      <select disabled><option>Select frac-list first</option></select>
    `;
    root.appendChild(field);
  });
}

function currentColumnMapping() {
  const mapping = {};
  document.querySelectorAll('[data-map-target]').forEach(select => {
    if (select.value) mapping[select.dataset.mapTarget] = select.value;
  });
  return Object.keys(mapping).length ? mapping : state.columnMapping || {};
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
      state.hasSavedWellSelection = true;
      renderWells();
      saveState();
    });
  });
}

async function openWellMatchingModal() {
  try {
    await ensureExtractionWellsLoaded();
    const fracWells = state.sleeves && (state.sleeves.wells || []).length ? state.sleeves.wells.map(well => well.name) : [];
    if (!fracWells.length) return fail(new Error('Load sleeves first to match wells.'));
    const models = state.loadedModels || [];
    if (!models.length) return fail(new Error('Load models first to match wells.'));
    showWellMatchingModal(fracWells, models);
  } catch (error) {
    fail(error);
  }
}

function showWellMatchingModal(fracWells, models) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const modelOptions = models.map(model => `<option value="${escapeHtml(model.label)}">${escapeHtml(model.label)}</option>`).join('');
  overlay.innerHTML = `
    <div class="modal-card well-match-modal">
      <div class="modal-title-row">
        <div>
          <div class="modal-title">Match wells</div>
          <p class="modal-text">Frac-list wells are on the left. Select the matching model trajectory on the right.</p>
        </div>
        <button class="icon-button" id="well-match-close" type="button">x</button>
      </div>
      <div class="well-match-toolbar">
        <label class="field"><span>Model</span><select id="well-match-model">${modelOptions}</select></label>
        <div class="well-match-actions">
          <button class="soft-button compact" id="well-match-load-json" type="button">Load JSON</button>
          <button class="soft-button compact" id="well-match-save-json" type="button">Save JSON</button>
        </div>
      </div>
      <div class="well-match-table" id="well-match-table"></div>
      <div class="modal-actions">
        <button class="soft-button" id="well-match-cancel" type="button">Close</button>
        <button class="primary-action compact-action" id="well-match-apply" type="button">Apply</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const modelSelect = overlay.querySelector('#well-match-model');
  modelSelect.value = models[0].label;
  let currentTrajectories = [];

  const render = async () => {
    const model = models.find(item => item.label === modelSelect.value) || models[0];
    currentTrajectories = await loadSectionTrajectories(model);
    renderWellMatchingRows(overlay, fracWells, currentTrajectories);
  };
  const close = () => overlay.remove();

  overlay.querySelector('#well-match-close').addEventListener('click', close);
  overlay.querySelector('#well-match-cancel').addEventListener('click', close);
  overlay.querySelector('#well-match-apply').addEventListener('click', () => {
    saveState();
    setReady(`Well matches: ${Object.keys(state.sectionWellNameMap || {}).length}`);
    close();
  });
  overlay.querySelector('#well-match-load-json').addEventListener('click', async () => {
    await loadWellMatchingJson();
    renderWellMatchingRows(overlay, fracWells, currentTrajectories);
  });
  overlay.querySelector('#well-match-save-json').addEventListener('click', saveWellMatchingJson);
  modelSelect.addEventListener('change', () => {
    render().catch(fail);
  });
  render().catch(fail);
}

function renderWellMatchingRows(overlay, fracWells, trajectories) {
  const root = overlay.querySelector('#well-match-table');
  const trajectoryOptions = modelTrajectoryOptions(trajectories);
  const rows = fracWells
    .slice()
    .sort((left, right) => String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' }))
    .map(fracWell => {
      const selected = modelWellNameForFracWell(fracWell, trajectories);
      const options = ['<option value="">-</option>'].concat(trajectoryOptions.map(option => {
        const selectedAttr = option.value === selected ? 'selected' : '';
        return `<option value="${escapeHtml(option.value)}" ${selectedAttr}>${escapeHtml(option.label)}</option>`;
      })).join('');
      return `
        <div class="well-match-row">
          <div class="well-match-frac">${escapeHtml(fracWell)}</div>
          <select data-frac-well="${escapeHtml(fracWell)}">${options}</select>
        </div>
      `;
    }).join('');
  root.innerHTML = `
    <div class="well-match-head"><span>Frac-list well</span><span>Model trajectory</span></div>
    ${rows}
  `;
  root.querySelectorAll('[data-frac-well]').forEach(select => {
    select.addEventListener('change', () => {
      setWellNameMatch(select.value, select.dataset.fracWell);
      saveState();
    });
  });
}

function modelTrajectoryOptions(trajectories) {
  const nameCounts = new Map();
  (trajectories || []).forEach(item => {
    const name = sectionTrajectoryName(item);
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1);
  });
  return (trajectories || [])
    .slice()
    .sort((left, right) => sectionTrajectoryName(left).localeCompare(sectionTrajectoryName(right), undefined, { numeric: true, sensitivity: 'base' }))
    .map(item => {
      const name = sectionTrajectoryName(item);
      return {
        value: name,
        label: (nameCounts.get(name) || 0) > 1 ? `${name} (${item.point_count || '?'} pts)` : name
      };
    });
}

function modelWellNameForFracWell(fracWell, trajectories) {
  const explicit = Object.entries(state.sectionWellNameMap || {})
    .find(([_modelName, mappedFrac]) => normalizeLookupTextSafe(mappedFrac) === normalizeLookupTextSafe(fracWell));
  if (explicit) return explicit[0];
  const exact = (trajectories || []).find(item => normalizeLookupTextSafe(sectionTrajectoryName(item)) === normalizeLookupTextSafe(fracWell));
  return exact ? sectionTrajectoryName(exact) : '';
}

function setWellNameMatch(modelWellName, fracWellName) {
  const map = state.sectionWellNameMap || {};
  Object.keys(map).forEach(key => {
    if (key === modelWellName || normalizeLookupTextSafe(map[key]) === normalizeLookupTextSafe(fracWellName)) {
      delete map[key];
    }
  });
  if (modelWellName && fracWellName) map[modelWellName] = fracWellName;
  state.sectionWellNameMap = map;
}

async function loadWellMatchingJson() {
  const path = await window.petrel.openFile({ filters: [{ name: 'Well matching JSON', extensions: ['json'] }, { name: 'All files', extensions: ['*'] }] });
  if (!path) return;
  const text = await window.petrel.readTextFile(path);
  const data = JSON.parse(text);
  const mappings = data.mappings || data.sectionWellNameMap || data;
  if (!mappings || typeof mappings !== 'object' || Array.isArray(mappings)) {
    throw new Error('Invalid well matching JSON.');
  }
  state.sectionWellNameMap = Object.fromEntries(Object.entries(mappings).map(([modelWell, fracWell]) => [String(modelWell), String(fracWell)]));
  saveState();
  setReady(`Loaded well matches: ${Object.keys(state.sectionWellNameMap).length}`);
}

async function saveWellMatchingJson() {
  const path = await window.petrel.saveFile({
    defaultPath: 'well_matching.json',
    filters: [{ name: 'Well matching JSON', extensions: ['json'] }]
  });
  if (!path) return;
  const payload = {
    version: 1,
    savedAt: new Date().toISOString(),
    mappings: state.sectionWellNameMap || {}
  };
  await window.petrel.writeTextFile(path, JSON.stringify(payload, null, 2));
  setReady(`Saved well matches: ${Object.keys(payload.mappings).length}`);
}

function setAllWells(checked) {
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  state.selectedWells = checked ? wells.map(well => well.name) : [];
  state.hasSavedWellSelection = true;
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
  const saved = state.extractionSelectedProperties;
  state.loadedModels.forEach(model => {
    const savedForModel = saved && Array.isArray(saved[model.label]) ? new Set(saved[model.label]) : null;
    (model.properties || []).forEach(prop => {
      const row = document.createElement('label');
      row.className = 'property-row';
      const isChecked = savedForModel ? savedForModel.has(prop.uuid) : shouldAutoSelect(prop.title);
      const checked = isChecked ? 'checked' : '';
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
      state.extractionSelectedProperties = currentExtractionSelectedProperties();
      if (state.tableColumns.length) renderMetricsProperties(state.tableColumns);
      saveState();
    });
  });
}

function renderSectionModels() {
  renderSectionProperties();
}

function renderSectionProperties() {
  const selected = $('section-property').value;
  const options = sectionPropertyOptions();
  fillSelectOptions('section-property', options, options.some(option => option.value === selected) ? selected : (options[0] && options[0].value));
}

function sectionPropertyOptions() {
  const selectedSpecs = new Map(selectedModelsWithProperties().map(model => [model.label, new Set(model.selectedPropertyUuids || [])]));
  const options = [];
  state.loadedModels.forEach(model => {
    const selectedForModel = selectedSpecs.get(model.label) || new Set();
    (model.properties || []).forEach(prop => {
      if (state.sectionUseExtractionSelection && !selectedForModel.has(prop.uuid)) return;
      options.push({
        value: sectionPropertyValue(model, prop),
        label: `${model.label} - ${prop.title}`
      });
    });
  });
  if (state.sectionUseExtractionSelection && !options.length) {
    appendLog('Warning: no selected Extraction properties were found for Sections.');
  }
  return options;
}

function sectionPropertyValue(model, prop) {
  return `${model.path || ''}::${prop.uuid || ''}`;
}

function findSectionPropertyByValue(value) {
  for (const model of state.loadedModels || []) {
    for (const prop of model.properties || []) {
      if (sectionPropertyValue(model, prop) === value || prop.uuid === value) {
        return { model, property: prop };
      }
    }
  }
  return null;
}

function setAllProperties(checked) {
  document.querySelectorAll('[data-property]').forEach(input => input.checked = checked);
  state.extractionSelectedProperties = currentExtractionSelectedProperties();
  if (state.tableColumns.length) renderMetricsProperties(state.tableColumns);
  saveState();
}

function currentExtractionSelectedProperties() {
  const selected = {};
  document.querySelectorAll('[data-property]').forEach(input => {
    if (!selected[input.dataset.model]) selected[input.dataset.model] = [];
    if (input.checked) selected[input.dataset.model].push(input.dataset.property);
  });
  return Object.keys(selected).length ? selected : state.extractionSelectedProperties || {};
}

function selectedModelsWithProperties() {
  const byLabel = {};
  document.querySelectorAll('[data-property]:checked').forEach(input => {
    if (!byLabel[input.dataset.model]) byLabel[input.dataset.model] = [];
    byLabel[input.dataset.model].push(input.dataset.property);
  });
  const saved = state.extractionSelectedProperties || {};
  return requestModels().map(model => Object.assign({}, model, {
    selectedPropertyUuids: byLabel[model.label] || saved[model.label] || []
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
      <label class="field"><span>Min</span><input id="curve-min-${index}" type="number" step="0.01"></label>
      <label class="field"><span>Max</span><input id="curve-max-${index}" type="number" step="0.01"></label>
      <label class="field"><span>Shift m</span><input id="curve-shift-${index}" type="number" step="0.1" value="0"></label>
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
    const { min, max } = numericRange(depths);
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
    const { min, max } = numericRange(values);
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
  const depthRange = numericRange(depths);
  if (!Number.isFinite(depthMin)) depthMin = depthRange.min;
  if (!Number.isFinite(depthMax)) depthMax = depthRange.max;
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
    const range = numericRange(values);
    if (!Number.isFinite(min)) min = range.min;
    if (!Number.isFinite(max)) max = range.max;
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
  plotEmptyIn('curve-plot', text);
}

function plotEmptyIn(plotId, text) {
  const target = $(plotId);
  if (!window.Plotly || !target) return;
  target.innerHTML = '';
  Plotly.react(target, [], {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    xaxis: { visible: false },
    yaxis: { visible: false },
    annotations: [{ text, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper', showarrow: false, font: { size: 18, color: '#667085' } }]
  }, { displaylogo: false, responsive: true });
}

async function loadSectionWells() {
  if (!state.loadedModels.length) return fail(new Error('Load models first.'));
  setBusy('Loading wells', 'Reading RESQML trajectories');
  try {
    state.sectionUseExtractionSelection = false;
    renderSectionProperties();
    state.sectionTrajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
    fillSectionWells(state.sectionTrajectories);
    $('section-summary').textContent = `Trajectories: ${state.sectionTrajectories.length}`;
    setReady(`Well trajectories: ${state.sectionTrajectories.length}`);
  } catch (error) {
    fail(error);
  }
}

async function loadSectionFromExtraction() {
  if (!state.loadedModels.length) return fail(new Error('Load models first.'));
  setBusy('Loading section context', 'Reading Extraction selection');
  try {
    state.sectionUseExtractionSelection = true;
    renderSectionProperties();
    await ensureExtractionWellsLoaded();
    const trajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
    const extractionWells = sectionExtractionWellNames();
    state.sectionTrajectories = await resolveSectionTrajectoriesFromExtraction(trajectories, extractionWells);
    fillSectionWells(state.sectionTrajectories);
    if (!extractionWells.length) {
      appendLog('Warning: no Extraction wells are selected or loaded; section well list is empty.');
    } else if (!state.sectionTrajectories.length) {
      appendLog('Warning: no model trajectories were matched to selected Extraction wells. Use Match wells on the Extraction page.');
    }
    $('section-summary').textContent = `Extraction wells: ${state.sectionTrajectories.length}`;
    setReady(`Section context from Extraction: ${state.sectionTrajectories.length} well(s)`);
    saveState();
  } catch (error) {
    fail(error);
  }
}

async function ensureExtractionWellsLoaded() {
  const path = $('sleeves-path').value.trim();
  if (!path || (state.sleeves && (state.sleeves.wells || []).length)) return;
  const result = await window.petrel.run('preview-sleeves', { path, columnMapping: currentColumnMapping() });
  state.sleeves = result;
  state.selectedWells = selectedWellsForLoadedSleeves(result.wells || []);
  renderMapping(result);
  renderWells();
}

async function loadSectionTrajectories(model) {
  const result = await window.petrel.run('well-trajectories', { path: model.path, includePoints: false });
  return annotateSectionTrajectories(result.trajectories || [], model);
}

async function loadSectionTrajectoriesFromModels(models) {
  const all = [];
  for (const model of models || []) {
    if (!model || !model.path) continue;
    try {
      all.push(...await loadSectionTrajectories(model));
    } catch (error) {
      appendLog(`Warning: cannot load trajectories from ${model.label}: ${error.message}`);
    }
  }
  return all;
}

function annotateSectionTrajectories(trajectories, model) {
  return (trajectories || []).map(item => Object.assign({}, item, {
    source_model: model.label,
    source_path: model.path
  }));
}

function sectionExtractionWellNames() {
  if (state.selectedWells && state.selectedWells.length) return state.selectedWells;
  if (state.sleeves && (state.sleeves.wells || []).length) return state.sleeves.wells.map(well => well.name);
  return [];
}

async function resolveSectionTrajectoriesFromExtraction(trajectories, wells) {
  const selected = [];
  const used = new Set();
  for (const well of wells || []) {
    const matched = findSectionTrajectoryForExtractionWell(trajectories, well, used);
    if (matched) {
      addSectionTrajectoryMatch(selected, used, matched, well);
    }
  }
  return selected;
}

function findSectionTrajectoryForExtractionWell(trajectories, well, used) {
  const key = normalizeLookupTextSafe(well);
  if (!key) return null;
  const mappedName = Object.entries(state.sectionWellNameMap || {})
    .find(([_modelName, fracName]) => normalizeLookupTextSafe(fracName) === key);
  if (mappedName) {
    const mapped = trajectories.find(item => !used.has(item.uuid) && normalizeLookupTextSafe(sectionTrajectoryName(item)) === normalizeLookupTextSafe(mappedName[0]));
    if (mapped) return mapped;
  }
  return trajectories.find(item => !used.has(item.uuid) && normalizeLookupTextSafe(sectionTrajectoryName(item)) === key) || null;
}

function addSectionTrajectoryMatch(selected, used, trajectory, extractionWell) {
  if (!trajectory || used.has(trajectory.uuid)) return;
  selected.push(trajectory);
  used.add(trajectory.uuid);
  state.sectionWellNameMap[sectionTrajectoryName(trajectory)] = extractionWell;
}

function fillSectionWells(trajectories) {
  const previous = $('section-well').value;
  const nameCounts = new Map();
  trajectories.forEach(item => {
    const name = sectionTrajectoryName(item);
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1);
  });
  const sorted = trajectories.slice().sort((left, right) => {
    const leftName = sectionTrajectoryName(left);
    const rightName = sectionTrajectoryName(right);
    const byName = leftName.localeCompare(rightName, undefined, { numeric: true, sensitivity: 'base' });
    if (byName !== 0) return byName;
    return Number(left.point_count || 0) - Number(right.point_count || 0);
  });
  const options = sorted.map(item => {
    const name = sectionTrajectoryName(item);
    const hasDuplicates = (nameCounts.get(name) || 0) > 1;
    const source = item.source_model ? ` - ${item.source_model}` : '';
    const saved = state.sectionSavedWells && state.sectionSavedWells[sectionTrajectoryValue(item)] ? ' [saved]' : '';
    return {
      value: sectionTrajectoryValue(item),
      label: (hasDuplicates ? `${name}${source} (${item.point_count || '?'} pts)` : `${name}${source}`) + saved
    };
  });
  const selected = options.some(option => option.value === previous) ? previous : (options[0] && options[0].value);
  fillSelectOptions('section-well', options, selected);
}

function sectionTrajectoryName(item) {
  return String((item && (item.well_name || item.title)) || '').trim() || 'Unnamed well';
}

function sectionTrajectoryValue(item) {
  return `${item && item.source_path ? item.source_path : ''}::${item && item.uuid ? item.uuid : ''}`;
}

function findSectionTrajectoryByValue(value) {
  return state.sectionTrajectories.find(item => sectionTrajectoryValue(item) === value)
    || state.sectionTrajectories.find(item => item.uuid === value)
    || null;
}

function clearSectionAutoBounds() {
  ['section-depth-min', 'section-depth-max', 'section-value-min', 'section-value-max'].forEach(id => {
    $(id).value = '';
  });
  state.sectionBoundaries = [];
}

async function drawSection() {
  const propertySelection = findSectionPropertyByValue($('section-property').value);
  if (!propertySelection || !propertySelection.model || !propertySelection.model.path) {
    return fail(new Error('Select section property.'));
  }
  const model = propertySelection.model;
  const trajectoryValue = $('section-well').value;
  if (!trajectoryValue) return fail(new Error('Load wells and select a trajectory.'));
  const trajectory = findSectionTrajectoryByValue(trajectoryValue);
  if (!trajectory) return fail(new Error('Selected trajectory was not found.'));
  const trajectoryUuid = trajectory.uuid;
  const propertyUuid = propertySelection.property.uuid;
  await ensureSectionWellNameMapped(trajectoryValue);
  setBusy('Drawing section', 'Sampling model along trajectory');
  try {
    const result = await window.petrel.run('model-section', {
      path: model.path,
      propertyUuid,
      trajectoryUuid,
      trajectoryPath: trajectory.source_path || model.path,
      sampleStep: Number($('section-step').value || 25),
      maxStations: Number($('section-max-stations').value || 1200),
      depthOffset: Number(model.depthOffset || 0),
      skipInactive: $('section-skip-inactive').checked
    });
    result.sleeveMarkers = await loadSectionSleeveMarkers(result.well_name);
    state.sectionResult = result;
    state.sectionRows = result.rows || [];
    state.sectionBoundaries = [];
    paintSection(result);
    setProgress('section-progress', 100);
    setReady(`Section cells: ${result.cell_count || state.sectionRows.length}, sleeves: ${(result.sleeveMarkers || []).length}`);
  } catch (error) {
    fail(error);
  }
}

async function ensureSectionWellNameMapped(trajectoryUuid) {
  const trajectory = findSectionTrajectoryByValue(trajectoryUuid);
  const modelWellName = sectionTrajectoryName(trajectory);
  if (!modelWellName || state.sectionWellNameMap[modelWellName]) return;
  const fracWells = state.sleeves && state.sleeves.wells ? state.sleeves.wells.map(well => well.name) : [];
  if (!fracWells.length) return;
  const exact = fracWells.find(well => normalizeLookupTextSafe(well) === normalizeLookupTextSafe(modelWellName));
  if (exact) {
    state.sectionWellNameMap[modelWellName] = exact;
    saveState();
  }
}

async function loadSectionSleeveMarkers(wellName) {
  const path = $('sleeves-path').value.trim();
  if (!path || !wellName) return [];
  const mappedName = state.sectionWellNameMap[wellName] || wellName;
  try {
    const result = await window.petrel.run('sleeve-markers', {
      path,
      wellName: mappedName,
      columnMapping: currentColumnMapping()
    });
    if ((result.markers || []).length) return result.markers || [];
    if (result.warning) appendLog(`Warning: ${result.warning}`);
    if (result.availableWells && result.availableWells.length && !state.sectionWellNameMap[wellName]) {
      appendLog(`Warning: no well match for "${wellName}". Use Match wells on the Extraction page.`);
    }
    return [];
  } catch (error) {
    appendLog(`Warning: sleeve markers were not loaded: ${error.message}`);
    return [];
  }
}

function normalizeLookupText(value) {
  return String(value || '')
    .trim()
    .toUpperCase()
    .replace(/[АВЕКМНОРСТХ]/g, char => ({ А: 'A', В: 'B', Е: 'E', К: 'K', М: 'M', Н: 'H', О: 'O', Р: 'P', С: 'C', Т: 'T', Х: 'X' }[char] || char))
    .replace(/[^A-Z0-9]/g, '');
}

function normalizeLookupTextSafe(value) {
  const cyrMap = {
    '\u0410': 'A',
    '\u0412': 'B',
    '\u0415': 'E',
    '\u041A': 'K',
    '\u041C': 'M',
    '\u041D': 'H',
    '\u041E': 'O',
    '\u0420': 'P',
    '\u0421': 'C',
    '\u0422': 'T',
    '\u0425': 'X'
  };
  return String(value || '')
    .trim()
    .toUpperCase()
    .replace(/[\u0410\u0412\u0415\u041A\u041C\u041D\u041E\u0420\u0421\u0422\u0425]/g, char => cyrMap[char] || char)
    .replace(/[^A-Z0-9]/g, '');
}

function paintSection(result) {
  const rows = result.rows || [];
  const validRows = rows.filter(row => Number.isFinite(numericCell(row.value)) && Number.isFinite(numericCell(row.tvd_center)));
  if (!validRows.length) {
    plotEmptyIn('section-plot', 'No section data');
    return;
  }
  let axis = sectionXAxisMode();
  let xValues = validRows.map(row => numericCell(row[axis]));
  if (!xValues.some(Number.isFinite)) {
    axis = 'horizontal_distance';
    xValues = validRows.map(row => numericCell(row.horizontal_distance));
  }
  if (!xValues.some(Number.isFinite)) {
    axis = 'distance';
    xValues = validRows.map(row => numericCell(row.distance));
  }
  const yValues = validRows.map(row => numericCell(row.tvd_center));
  const values = validRows.map(row => numericCell(row.value));
  const finiteX = xValues.filter(Number.isFinite);
  const finiteY = yValues.filter(Number.isFinite);
  const finiteValues = values.filter(Number.isFinite);
  const propertyDepthCoreIntervalRaw = sectionPropertyDepthInterval(validRows, 0);
  const sleeveDepthInterval = sectionSleeveDepthInterval(rows, axis, result.sleeveMarkers || [], 50);
  const propertyDepthCoreInterval = sleeveDepthInterval || propertyDepthCoreIntervalRaw;
  const propertyDepthInterval = sleeveDepthInterval || sectionPropertyDepthInterval(validRows, 30);
  const displayXInterval = sectionXDisplayInterval(rows, axis, propertyDepthCoreInterval, finiteX);
  let depthMin = numericInput('section-depth-min');
  let depthMax = numericInput('section-depth-max');
  if (sleeveDepthInterval) {
    if (!Number.isFinite(depthMin) || depthMin < sleeveDepthInterval.min || depthMin > sleeveDepthInterval.max) depthMin = sleeveDepthInterval.min;
    if (!Number.isFinite(depthMax) || depthMax > sleeveDepthInterval.max || depthMax < sleeveDepthInterval.min) depthMax = sleeveDepthInterval.max;
    if (depthMax <= depthMin) {
      depthMin = sleeveDepthInterval.min;
      depthMax = sleeveDepthInterval.max;
    }
    $('section-depth-min').value = formatInputNumber(depthMin, 1);
    $('section-depth-max').value = formatInputNumber(depthMax, 1);
  } else {
    if (!Number.isFinite(depthMin)) depthMin = propertyDepthCoreInterval.min - 10;
    if (!Number.isFinite(depthMax)) depthMax = propertyDepthCoreInterval.max + 10;
    if (!$('section-depth-min').value) $('section-depth-min').value = formatInputNumber(depthMin, 1);
    if (!$('section-depth-max').value) $('section-depth-max').value = formatInputNumber(depthMax, 1);
  }
  let valueMin = numericInput('section-value-min');
  let valueMax = numericInput('section-value-max');
  const roundedValues = roundedValueBounds(finiteValues);
  if (!Number.isFinite(valueMin)) valueMin = roundedValues.min;
  if (!Number.isFinite(valueMax)) valueMax = roundedValues.max;
  if (Number.isFinite(roundedValues.min) && roundedValues.min >= 0 && Number.isFinite(valueMin) && valueMin < 0) {
    valueMin = roundedValues.min;
    $('section-value-min').value = formatInputNumber(valueMin, 4);
  }
  if (!$('section-value-min').value) $('section-value-min').value = formatInputNumber(valueMin, 4);
  if (!$('section-value-max').value) $('section-value-max').value = formatInputNumber(valueMax, 4);
  const common = {
    axis,
    xValues,
    yValues,
    values,
    valueMin,
    valueMax,
    depthMin,
    depthMax,
    xMin: displayXInterval.min,
    xMax: displayXInterval.max,
    propertyDepthCoreInterval,
    propertyDepthInterval,
    validRows
  };
  renderSectionLayerMesh(common, result);
  $('section-summary').textContent = `${result.well_name}: ${result.station_count} stations, ${result.cell_count} cells, ${(result.sleeveMarkers || []).length} sleeves`;
}

function sectionPointTrace(common, result) {
  const finiteX = common.xValues.filter(Number.isFinite);
  const xRange = numericRange(finiteX);
  const xSpan = xRange.max - xRange.min;
  const markerSize = xSpan > 0 ? Math.max(4, Math.min(9, 520 / Math.max(60, result.station_count || 1))) : 6;
  return {
    type: 'scatter',
    mode: 'markers',
    x: common.xValues,
    y: common.yValues,
    marker: {
      symbol: 'square',
      size: markerSize,
      color: common.values,
      colorscale: 'Viridis',
      cmin: common.valueMin,
      cmax: common.valueMax,
      colorbar: { title: result.property_title || 'Value', thickness: 14 }
    },
    customdata: common.validRows.map(row => [row.i, row.j, row.k, row.md, row.distance, row.horizontal_distance, row.value]),
    hovertemplate: 'I/J/K: %{customdata[0]}/%{customdata[1]}/%{customdata[2]}<br>' +
      'MD: %{customdata[3]:.2f}<br>3D distance: %{customdata[4]:.2f}<br>' +
      'Horizontal distance: %{customdata[5]:.2f}<br>Depth: %{y:.2f}<br>Value: %{customdata[6]}<extra></extra>'
  };
}

function sectionTrajectoryTrace(rows, common) {
  const points = sectionTrajectoryPoints(rows, common);
  if (points.length < 2) return null;
  return {
    type: 'scatter',
    mode: 'lines',
    x: points.map(point => point.x),
    y: points.map(point => point.depth),
    line: { color: '#ef4444', width: 3 },
    name: 'Well trajectory',
    hovertemplate: `${sectionXAxisTitle(common.axis)}: %{x:.2f}<br>Trajectory TVD: %{y:.2f}<extra>Well trajectory</extra>`
  };
}

function sectionPropertyDepthInterval(rows, pad) {
  const tops = rows.map(row => numericCell(row.tvd_top)).filter(Number.isFinite);
  const bases = rows.map(row => numericCell(row.tvd_base)).filter(Number.isFinite);
  const values = tops.concat(bases);
  if (!values.length) return { min: NaN, max: NaN };
  const padding = Number.isFinite(pad) ? pad : 0;
  const range = numericRange(values);
  return {
    min: range.min - padding,
    max: range.max + padding
  };
}

function roundedValueBounds(values) {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return { min: NaN, max: NaN };
  const range = numericRange(finite);
  const rawMin = range.min;
  const rawMax = range.max;
  const maxAbs = Math.max(Math.abs(rawMin), Math.abs(rawMax));
  const scale = maxAbs < 1 ? 10 : 1;
  return {
    min: Math.floor(rawMin * scale) / scale,
    max: Math.ceil(rawMax * scale) / scale
  };
}

function sectionXDisplayInterval(rows, axis, propertyDepthInterval, fallbackXValues) {
  const points = sectionStationTrajectoryPoints(rows, axis);
  const fallback = paddedFiniteRange(fallbackXValues, 50);
  if (points.length < 2 || !Number.isFinite(propertyDepthInterval.min) || !Number.isFinite(propertyDepthInterval.max)) {
    return fallback;
  }

  const topDepth = propertyDepthInterval.min;
  const baseDepth = propertyDepthInterval.max;
  const entryX = firstDepthCrossingX(points, topDepth);
  const inInterval = points.filter(point => point.depth >= topDepth && point.depth <= baseDepth);
  const exitX = lastDepthCrossingX(points, baseDepth);
  const minSource = Number.isFinite(entryX) ? entryX : (inInterval[0] ? inInterval[0].x : fallback.min + 50);
  const maxSource = Number.isFinite(exitX)
    ? exitX
    : (inInterval.length ? inInterval[inInterval.length - 1].x : fallback.max - 50);
  let minValue = Math.max(0, minSource - 50);
  let maxValue = maxSource + 50;
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || maxValue <= minValue) return fallback;
  return { min: minValue, max: maxValue };
}

function sectionStationTrajectoryPoints(rows, axis) {
  const byStation = new Map();
  rows.forEach(row => {
    const station = Number(row.station_index);
    const x = numericCell(row[axis]);
    const depth = sectionTrajectoryDepth(row.z);
    const md = numericCell(row.md);
    if (!Number.isFinite(station) || !Number.isFinite(x) || !Number.isFinite(depth)) return;
    if (!byStation.has(station)) {
      byStation.set(station, {
        station,
        x,
        depth,
        md,
        worldX: numericCell(row.x),
        worldY: numericCell(row.y)
      });
    }
  });
  return Array.from(byStation.values()).sort((a, b) => a.x - b.x || a.station - b.station);
}

function firstDepthCrossingX(points, targetDepth) {
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    if (current.depth >= targetDepth) {
      if (index === 0) return current.x;
      return interpolateCrossingX(points[index - 1], current, targetDepth);
    }
  }
  return NaN;
}

function lastDepthCrossingX(points, targetDepth) {
  let lastInside = NaN;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    if (current.depth <= targetDepth) {
      lastInside = current.x;
      continue;
    }
    if (Number.isFinite(lastInside) && index > 0) {
      return interpolateCrossingX(points[index - 1], current, targetDepth);
    }
  }
  return lastInside;
}

function interpolateCrossingX(left, right, targetDepth) {
  const span = right.depth - left.depth;
  if (!Number.isFinite(span) || Math.abs(span) < 1e-9) return right.x;
  const fraction = Math.max(0, Math.min(1, (targetDepth - left.depth) / span));
  return left.x + (right.x - left.x) * fraction;
}

function paddedFiniteRange(values, padding) {
  const finite = (values || []).filter(Number.isFinite);
  if (!finite.length) return { min: 0, max: 1 };
  const range = numericRange(finite);
  const pad = Number.isFinite(padding) ? padding : 0;
  return { min: Math.max(0, range.min - pad), max: range.max + pad };
}

function sectionTrajectoryPoints(rows, common) {
  const byStation = new Map();
  rows.forEach(row => {
    const station = Number(row.station_index);
    const x = numericCell(row[common.axis]);
    const depth = sectionTrajectoryDepth(row.z);
    if (!Number.isFinite(station) || !Number.isFinite(x) || !Number.isFinite(depth)) return;
    if (Number.isFinite(common.propertyDepthInterval.min) && depth < common.propertyDepthInterval.min) return;
    if (Number.isFinite(common.propertyDepthInterval.max) && depth > common.propertyDepthInterval.max) return;
    if (!byStation.has(station)) {
      byStation.set(station, {
        station,
        x,
        depth,
        md: numericCell(row.md),
        distance: numericCell(row.distance),
        horizontal_distance: numericCell(row.horizontal_distance),
        worldX: numericCell(row.x),
        worldY: numericCell(row.y)
      });
    }
  });
  const points = Array.from(byStation.values()).sort((a, b) => a.x - b.x || a.station - b.station);
  const xValues = monotonicAxisValues(points.map(point => point.x));
  points.forEach((point, index) => {
    point.x = xValues[index];
  });
  return points;
}

function sectionTrajectoryDepth(zValue) {
  const z = numericCell(zValue);
  if (!Number.isFinite(z)) return NaN;
  return z < 0 ? -z : z;
}

function sectionSleeveDepthInterval(rows, axis, markers, padding) {
  if (!markers || !markers.length) return null;
  const trajectory = sectionStationTrajectoryPoints(rows, axis)
    .filter(point => Number.isFinite(point.md))
    .sort((a, b) => a.md - b.md);
  if (trajectory.length < 2) return null;
  const depths = [];
  markers.forEach(marker => {
    const md = numericCell(marker.md);
    if (!Number.isFinite(md)) return;
    const point = interpolateTrajectoryByMd(trajectory, md);
    if (point && Number.isFinite(point.depth)) depths.push(point.depth);
  });
  if (!depths.length) return null;
  const range = numericRange(depths);
  const pad = Number.isFinite(padding) ? padding : 0;
  return {
    min: range.min - pad,
    max: range.max + pad
  };
}

function sectionSleevePoints(rows, common, markers) {
  if (!markers || !markers.length) return [];
  const trajectory = sectionStationTrajectoryPoints(rows, common.axis)
    .filter(point => Number.isFinite(point.md))
    .sort((a, b) => a.md - b.md);
  if (trajectory.length < 2) return [];
  return markers
    .map(marker => {
      const md = numericCell(marker.md);
      if (!Number.isFinite(md)) return null;
      const point = interpolateTrajectoryByMd(trajectory, md);
      if (!point) return null;
      return {
        port: marker.port,
        well: marker.well,
        md,
        x: point.x,
        depth: point.depth,
        worldX: point.worldX,
        worldY: point.worldY
      };
    })
    .filter(Boolean);
}

function interpolateTrajectoryByMd(points, md) {
  if (md < points[0].md || md > points[points.length - 1].md) return null;
  for (let index = 1; index < points.length; index += 1) {
    const left = points[index - 1];
    const right = points[index];
    if (md > right.md) continue;
    const span = right.md - left.md;
    const fraction = Math.abs(span) < 1e-9 ? 0 : (md - left.md) / span;
    return {
      x: left.x + (right.x - left.x) * fraction,
      depth: left.depth + (right.depth - left.depth) * fraction,
      worldX: interpolateOptionalNumber(left.worldX, right.worldX, fraction),
      worldY: interpolateOptionalNumber(left.worldY, right.worldY, fraction)
    };
  }
  const last = points[points.length - 1];
  return { x: last.x, depth: last.depth, worldX: last.worldX, worldY: last.worldY };
}

function interpolateOptionalNumber(left, right, fraction) {
  if (Number.isFinite(left) && Number.isFinite(right)) return left + (right - left) * fraction;
  return Number.isFinite(left) ? left : right;
}

function renderSectionLayerMesh(common, result) {
  const target = $('section-plot');
  if (!target) return;
  if (window.Plotly) Plotly.purge(target);
  target.innerHTML = `
    <canvas class="section-mesh-canvas"></canvas>
    <div class="section-mesh-tooltip" hidden></div>
  `;
  const canvas = target.querySelector('canvas');
  const tooltip = target.querySelector('.section-mesh-tooltip');
  const mesh = buildSectionLayerMesh(common.validRows, common.axis, common.depthMin, common.depthMax, common.valueMin, common.valueMax, common.xMin, common.xMax);
  mesh.trajectory = sectionTrajectoryPoints(result.rows || [], common);
  mesh.sleeves = sectionSleevePoints(result.rows || [], common, result.sleeveMarkers || []);
  state.sectionMesh = { common, result, mesh };
  drawSectionLayerMesh(canvas, mesh, common, result);
  canvas.addEventListener('mousedown', event => startSectionBoundaryDrag(event, canvas, mesh));
  canvas.addEventListener('mousemove', event => {
    if (state.sectionBoundaryDrag) {
      dragSectionBoundary(event, canvas);
      return;
    }
    showSectionMeshTooltip(event, canvas, tooltip, mesh, common);
  });
  canvas.addEventListener('mouseleave', () => {
    if (!state.sectionBoundaryDrag) tooltip.hidden = true;
  });
}

function buildSectionLayerMesh(rows, axis, depthMin, depthMax, valueMin, valueMax, xMin, xMax) {
  const byStation = new Map();
  rows.forEach(row => {
    const station = Number(row.station_index);
    const x = numericCell(row[axis]);
    const k = Number(row.k);
    const top = numericCell(row.tvd_top);
    const base = numericCell(row.tvd_base);
    const value = numericCell(row.value);
    if (!Number.isFinite(station) || !Number.isFinite(x) || !Number.isFinite(k)) return;
    if (!Number.isFinite(top) || !Number.isFinite(base) || !Number.isFinite(value)) return;
    if (base < depthMin || top > depthMax) return;
    if (!byStation.has(station)) byStation.set(station, { station, x, rowsByK: new Map() });
    byStation.get(station).rowsByK.set(k, { k, top, base, value, row });
  });

  const stations = Array.from(byStation.values()).sort((a, b) => a.x - b.x || a.station - b.station);
  const xRaw = monotonicAxisValues(stations.map(station => station.x));
  stations.forEach((station, index) => {
    station.xPlot = xRaw[index];
  });

  const quads = [];
  for (let index = 0; index < stations.length - 1; index += 1) {
    const left = stations[index];
    const right = stations[index + 1];
    left.rowsByK.forEach((leftCell, k) => {
      const rightCell = right.rowsByK.get(k);
      if (!rightCell) return;
      const value = (leftCell.value + rightCell.value) / 2;
      const topLeft = Math.max(depthMin, Math.min(depthMax, leftCell.top));
      const baseLeft = Math.max(depthMin, Math.min(depthMax, leftCell.base));
      const topRight = Math.max(depthMin, Math.min(depthMax, rightCell.top));
      const baseRight = Math.max(depthMin, Math.min(depthMax, rightCell.base));
      if (Math.max(baseLeft, baseRight) <= depthMin || Math.min(topLeft, topRight) >= depthMax) return;
      quads.push({
        k,
        value,
        leftCell,
        rightCell,
        points: [
          { x: left.xPlot, y: topLeft },
          { x: right.xPlot, y: topRight },
          { x: right.xPlot, y: baseRight },
          { x: left.xPlot, y: baseLeft }
        ]
      });
    });
  }

  const finiteX = xRaw.filter(Number.isFinite);
  const xRange = numericRange(finiteX);
  return {
    quads,
    xMin: Number.isFinite(xMin) ? xMin : (finiteX.length ? xRange.min : 0),
    xMax: Number.isFinite(xMax) ? xMax : (finiteX.length ? xRange.max : 1),
    yMin: depthMin,
    yMax: depthMax,
    valueMin,
    valueMax
  };
}

function drawSectionLayerMesh(canvas, mesh, common, result) {
  const container = $('section-plot');
  const rect = container.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(320, Math.floor(rect.height));
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  const frame = sectionMeshFrame(width, height);
  mesh.frame = frame;
  mesh.screenQuads = [];
  drawSectionMeshGrid(ctx, frame, mesh, common, result);

  ctx.save();
  ctx.beginPath();
  ctx.rect(frame.left, frame.top, frame.width, frame.height);
  ctx.clip();
  for (const quad of mesh.quads) {
    const points = quad.points.map(point => sectionMeshToScreen(point.x, point.y, frame, mesh));
    if (points.some(point => !Number.isFinite(point.x) || !Number.isFinite(point.y))) continue;
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let index = 1; index < points.length; index += 1) ctx.lineTo(points[index].x, points[index].y);
    ctx.closePath();
    const color = viridisColor((quad.value - mesh.valueMin) / (mesh.valueMax - mesh.valueMin));
    ctx.fillStyle = `rgba(${color[0]}, ${color[1]}, ${color[2]}, 0.96)`;
    ctx.fill();
    mesh.screenQuads.push({ quad, points, bbox: polygonBBox(points) });
  }
  ctx.restore();

  drawSectionMeshTrajectory(ctx, frame, mesh);
  drawSectionMeshSleeves(ctx, frame, mesh);
  drawSectionMeshBoundaries(ctx, frame, mesh);
  drawSectionMeshAxes(ctx, frame, mesh, common, result);
  drawSectionMeshColorbar(ctx, frame, mesh, result);
}

function sectionMeshFrame(width, height) {
  const left = 86;
  const rightMargin = 138;
  const top = 56;
  const bottomMargin = 72;
  return {
    left,
    top,
    right: width - rightMargin,
    bottom: height - bottomMargin,
    width: Math.max(1, width - left - rightMargin),
    height: Math.max(1, height - top - bottomMargin)
  };
}

function drawSectionMeshGrid(ctx, frame, mesh, common, result) {
  ctx.fillStyle = '#0f172a';
  ctx.font = '14px Arial, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(`${result.well_name || ''} | ${result.property_title || ''}`, frame.left + frame.width / 2, 26);
  ctx.strokeStyle = '#dce4ee';
  ctx.lineWidth = 1;
  for (const tick of sectionTicks(mesh.xMin, mesh.xMax, 7)) {
    const x = sectionMeshToScreen(tick, mesh.yMin, frame, mesh).x;
    if (x < frame.left - 0.5 || x > frame.right + 0.5) continue;
    ctx.beginPath();
    ctx.moveTo(x, frame.top);
    ctx.lineTo(x, frame.bottom);
    ctx.stroke();
  }
  for (const tick of sectionTicks(mesh.yMin, mesh.yMax, 8)) {
    const y = sectionMeshToScreen(mesh.xMin, tick, frame, mesh).y;
    if (y < frame.top - 0.5 || y > frame.bottom + 0.5) continue;
    ctx.beginPath();
    ctx.moveTo(frame.left, y);
    ctx.lineTo(frame.right, y);
    ctx.stroke();
  }
}

function drawSectionMeshAxes(ctx, frame, mesh, common) {
  ctx.strokeStyle = '#8a96a8';
  ctx.lineWidth = 1;
  ctx.strokeRect(frame.left, frame.top, frame.width, frame.height);
  ctx.fillStyle = '#0f172a';
  ctx.font = '12px Arial, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (const tick of sectionTicks(mesh.xMin, mesh.xMax, 7)) {
    const x = sectionMeshToScreen(tick, mesh.yMin, frame, mesh).x;
    if (x < frame.left - 0.5 || x > frame.right + 0.5) continue;
    ctx.fillText(formatAxisTick(tick), x, frame.bottom + 10);
  }
  ctx.fillText(sectionXAxisTitle(common.axis), frame.left + frame.width / 2, frame.bottom + 42);
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const tick of sectionTicks(mesh.yMin, mesh.yMax, 8)) {
    const y = sectionMeshToScreen(mesh.xMin, tick, frame, mesh).y;
    if (y < frame.top - 0.5 || y > frame.bottom + 0.5) continue;
    ctx.fillText(formatAxisTick(tick), frame.left - 10, y);
  }
  ctx.save();
  ctx.translate(20, frame.top + frame.height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillText('TVD', 0, 0);
  ctx.restore();
}

function drawSectionMeshColorbar(ctx, frame, mesh, result) {
  const barLeft = frame.right + 28;
  const barTop = frame.top + 10;
  const barWidth = 16;
  const barHeight = frame.height - 20;
  const steps = Math.max(40, Math.floor(barHeight));
  for (let index = 0; index < steps; index += 1) {
    const t = 1 - index / Math.max(1, steps - 1);
    const color = viridisColor(t);
    ctx.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    ctx.fillRect(barLeft, barTop + index * barHeight / steps, barWidth, Math.ceil(barHeight / steps) + 1);
  }
  ctx.strokeStyle = '#8a96a8';
  ctx.strokeRect(barLeft, barTop, barWidth, barHeight);
  ctx.fillStyle = '#0f172a';
  ctx.font = '12px Arial, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const tick of sectionTicks(mesh.valueMin, mesh.valueMax, 6)) {
    const t = (tick - mesh.valueMin) / (mesh.valueMax - mesh.valueMin || 1);
    const y = barTop + barHeight * (1 - t);
    ctx.fillText(formatAxisTick(tick), barLeft + barWidth + 8, y);
  }
  ctx.save();
  ctx.translate(barLeft + 40, barTop - 8);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText(result.property_title || 'Value', 0, 0);
  ctx.restore();
}

function drawSectionMeshTrajectory(ctx, frame, mesh) {
  const points = (mesh.trajectory || [])
    .filter(point => point.depth >= mesh.yMin && point.depth <= mesh.yMax)
    .map(point => sectionMeshToScreen(point.x, point.depth, frame, mesh))
    .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (points.length < 2) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(frame.left, frame.top, frame.width, frame.height);
  ctx.clip();
  drawPolyline(ctx, points, '#ffffff', 8, 0.92);
  drawPolyline(ctx, points, '#ef4444', 4, 1);
  ctx.restore();
}

function drawSectionMeshSleeves(ctx, frame, mesh) {
  const sleeves = (mesh.sleeves || [])
    .filter(item => item.depth >= mesh.yMin && item.depth <= mesh.yMax && item.x >= mesh.xMin && item.x <= mesh.xMax)
    .map(item => ({ ...item, screen: sectionMeshToScreen(item.x, item.depth, frame, mesh) }))
    .filter(item => Number.isFinite(item.screen.x) && Number.isFinite(item.screen.y));
  if (!sleeves.length) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(frame.left, frame.top, frame.width, frame.height);
  ctx.clip();
  ctx.font = '11px Arial, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const sleeve of sleeves) {
    const x = sleeve.screen.x;
    const y = sleeve.screen.y;
    ctx.beginPath();
    ctx.arc(x, y, 4.2, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#b91c1c';
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 2.1, 0, Math.PI * 2);
    ctx.fillStyle = '#ef4444';
    ctx.fill();
    const label = sleeve.port == null ? '' : String(sleeve.port);
    if (label) {
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#ffffff';
      ctx.strokeText(label, x + 7, y - 1);
      ctx.fillStyle = '#7f1d1d';
      ctx.fillText(label, x + 7, y - 1);
    }
  }
  ctx.restore();
}

function drawSectionMeshBoundaries(ctx, frame, mesh) {
  mesh.boundaryHandles = [];
  if (!$('section-show-boundaries').checked) return;
  const boundaries = state.sectionBoundaries || [];
  if (!boundaries.length) return;
  const styles = {
    TVDSS_TOP_TOTAL: { color: '#f59e0b', label: 'TT' },
    TVDSS_BOT_TOTAL: { color: '#f97316', label: 'BT' },
    TVDSS_TOP_LOCAL: { color: '#2563eb', label: 'TL' },
    TVDSS_BOT_LOCAL: { color: '#7c3aed', label: 'BL' }
  };
  ctx.save();
  ctx.beginPath();
  ctx.rect(frame.left, frame.top, frame.width, frame.height);
  ctx.clip();
  ctx.font = '10px Arial, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const boundary of boundaries) {
    if (!Number.isFinite(boundary.x) || boundary.x < mesh.xMin || boundary.x > mesh.xMax) continue;
    const topTotal = boundary.TVDSS_TOP_TOTAL;
    const botTotal = boundary.TVDSS_BOT_TOTAL;
    if (Number.isFinite(topTotal) || Number.isFinite(botTotal)) {
      const y1 = sectionMeshToScreen(boundary.x, Number.isFinite(topTotal) ? topTotal : mesh.yMin, frame, mesh).y;
      const y2 = sectionMeshToScreen(boundary.x, Number.isFinite(botTotal) ? botTotal : mesh.yMax, frame, mesh).y;
      const x = sectionMeshToScreen(boundary.x, mesh.yMin, frame, mesh).x;
      ctx.beginPath();
      ctx.moveTo(x, Math.max(frame.top, Math.min(frame.bottom, y1)));
      ctx.lineTo(x, Math.max(frame.top, Math.min(frame.bottom, y2)));
      ctx.strokeStyle = 'rgba(15, 23, 42, 0.35)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    Object.entries(styles).forEach(([key, style]) => {
      const depth = boundary[key];
      if (!Number.isFinite(depth) || depth < mesh.yMin || depth > mesh.yMax) return;
      const screen = sectionMeshToScreen(boundary.x, depth, frame, mesh);
      mesh.boundaryHandles.push({ boundary, key, x: screen.x, y: screen.y });
      ctx.beginPath();
      ctx.rect(screen.x - 4, screen.y - 4, 8, 8);
      ctx.fillStyle = '#ffffff';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = style.color;
      ctx.stroke();
      ctx.fillStyle = style.color;
      ctx.fillText(style.label, screen.x + 7, screen.y);
    });
  }
  ctx.restore();
}

function autoPlaceSectionBoundaries() {
  if (!state.sectionMesh || !state.sectionMesh.mesh) return fail(new Error('Draw a section first.'));
  const { common, mesh } = state.sectionMesh;
  if (!mesh.sleeves || !mesh.sleeves.length) return fail(new Error('No sleeve markers were loaded for this well.'));
  const valueRange = numericRange((common.validRows || []).map(row => numericCell(row.value)));
  const boundaries = [];
  for (const sleeve of mesh.sleeves) {
    const cells = sectionBoundaryCellsAtSleeve(common.validRows || [], common.axis, sleeve, valueRange);
    const intervals = sectionMergeIntervals(cells.map(cell => ({ top: cell.top, base: cell.base })), 2);
    if (!intervals.length) continue;
    const local = sectionNearestInterval(intervals, sleeve.depth);
    const totalRange = numericRange(intervals.flatMap(interval => [interval.top, interval.base]));
    boundaries.push({
      well: sleeve.well || (state.sectionResult && state.sectionResult.well_name) || '',
      port: sleeve.port,
      md: sleeve.md,
      x: sleeve.x,
      y: sleeve.depth,
      worldX: sleeve.worldX,
      worldY: sleeve.worldY,
      TVDSS_PORT: sleeve.depth,
      TVDSS_TOP_TOTAL: totalRange.min,
      TVDSS_BOT_TOTAL: totalRange.max,
      TVDSS_TOP_LOCAL: local ? local.top : totalRange.min,
      TVDSS_BOT_LOCAL: local ? local.base : totalRange.max
    });
  }
  state.sectionBoundaries = boundaries;
  redrawCurrentSectionMesh();
  setReady(`Auto boundaries: ${boundaries.length} sleeves`);
}

function sectionBoundaryCellsAtSleeve(rows, axis, sleeve, valueRange) {
  const stationMap = new Map();
  for (const row of rows || []) {
    const station = Number(row.station_index);
    const x = numericCell(row[axis]);
    const top = numericCell(row.tvd_top);
    const base = numericCell(row.tvd_base);
    const value = numericCell(row.value);
    if (!Number.isFinite(station) || !Number.isFinite(x) || !Number.isFinite(top) || !Number.isFinite(base) || !Number.isFinite(value)) continue;
    if (isUnitScaleRange(valueRange) && value <= 1e-9) continue;
    if (!stationMap.has(station)) stationMap.set(station, { station, x, cells: [] });
    stationMap.get(station).cells.push({ top: Math.min(top, base), base: Math.max(top, base), value });
  }
  const stations = Array.from(stationMap.values());
  if (!stations.length) return [];
  stations.sort((left, right) => Math.abs(left.x - sleeve.x) - Math.abs(right.x - sleeve.x));
  return stations[0].cells.sort((a, b) => a.top - b.top);
}

function isUnitScaleRange(range) {
  return Number.isFinite(range.min) && Number.isFinite(range.max) && range.min >= -0.001 && range.max <= 1.001;
}

function sectionMergeIntervals(intervals, gap) {
  const sorted = (intervals || [])
    .filter(interval => Number.isFinite(interval.top) && Number.isFinite(interval.base))
    .map(interval => ({ top: Math.min(interval.top, interval.base), base: Math.max(interval.top, interval.base) }))
    .sort((left, right) => left.top - right.top);
  const merged = [];
  for (const interval of sorted) {
    const last = merged[merged.length - 1];
    if (!last || interval.top > last.base + gap) {
      merged.push({ ...interval });
    } else {
      last.base = Math.max(last.base, interval.base);
    }
  }
  return merged;
}

function sectionNearestInterval(intervals, depth) {
  if (!intervals.length || !Number.isFinite(depth)) return intervals[0] || null;
  let best = intervals[0];
  let bestDistance = Infinity;
  for (const interval of intervals) {
    const distance = depth >= interval.top && depth <= interval.base
      ? 0
      : Math.min(Math.abs(depth - interval.top), Math.abs(depth - interval.base));
    if (distance < bestDistance) {
      best = interval;
      bestDistance = distance;
    }
  }
  return best;
}

function startSectionBoundaryDrag(event, canvas, mesh) {
  if (!$('section-show-boundaries').checked || !mesh.boundaryHandles || !mesh.boundaryHandles.length) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  let best = null;
  let bestDistance = Infinity;
  for (const handle of mesh.boundaryHandles) {
    const distance = Math.hypot(handle.x - x, handle.y - y);
    if (distance < bestDistance) {
      best = handle;
      bestDistance = distance;
    }
  }
  if (!best || bestDistance > 10) return;
  state.sectionBoundaryDrag = { boundary: best.boundary, key: best.key };
  event.preventDefault();
}

function dragSectionBoundary(event, canvas) {
  const current = state.sectionMesh;
  if (!current || !state.sectionBoundaryDrag) return;
  const rect = canvas.getBoundingClientRect();
  const y = event.clientY - rect.top;
  const depth = sectionMeshDepthFromScreen(y, current.mesh.frame, current.mesh);
  const drag = state.sectionBoundaryDrag;
  drag.boundary[drag.key] = Math.max(current.mesh.yMin, Math.min(current.mesh.yMax, depth));
  normalizeBoundaryOrder(drag.boundary);
  redrawCurrentSectionMesh();
}

function stopSectionBoundaryDrag() {
  state.sectionBoundaryDrag = null;
}

function normalizeBoundaryOrder(boundary) {
  if (Number.isFinite(boundary.TVDSS_TOP_TOTAL) && Number.isFinite(boundary.TVDSS_BOT_TOTAL) && boundary.TVDSS_TOP_TOTAL > boundary.TVDSS_BOT_TOTAL) {
    [boundary.TVDSS_TOP_TOTAL, boundary.TVDSS_BOT_TOTAL] = [boundary.TVDSS_BOT_TOTAL, boundary.TVDSS_TOP_TOTAL];
  }
  if (Number.isFinite(boundary.TVDSS_TOP_LOCAL) && Number.isFinite(boundary.TVDSS_BOT_LOCAL) && boundary.TVDSS_TOP_LOCAL > boundary.TVDSS_BOT_LOCAL) {
    [boundary.TVDSS_TOP_LOCAL, boundary.TVDSS_BOT_LOCAL] = [boundary.TVDSS_BOT_LOCAL, boundary.TVDSS_TOP_LOCAL];
  }
}

function sectionMeshDepthFromScreen(y, frame, mesh) {
  const fraction = (y - frame.top) / (frame.height || 1);
  return mesh.yMin + fraction * (mesh.yMax - mesh.yMin);
}

function redrawCurrentSectionMesh() {
  const current = state.sectionMesh;
  const canvas = document.querySelector('#section-plot canvas');
  if (!current || !canvas) return;
  drawSectionLayerMesh(canvas, current.mesh, current.common, current.result);
}

async function saveSectionBoundaries() {
  if (!state.sectionBoundaries || !state.sectionBoundaries.length) return fail(new Error('Place boundary points first.'));
  const path = $('sleeves-path').value.trim();
  if (!path) return fail(new Error('Select frac-list on Extraction page first.'));
  const outputPath = sectionBoundaryOutputPath(path);
  setBusy('Saving boundaries', basename(outputPath));
  try {
    const records = state.sectionBoundaries.map(boundary => ({
      well: boundary.well,
      port: boundary.port,
      md: boundary.md,
      X: boundary.worldX,
      Y: boundary.worldY,
      TVDSS_PORT: boundary.TVDSS_PORT,
      TVDSS_TOP_TOTAL: boundary.TVDSS_TOP_TOTAL,
      TVDSS_BOT_TOTAL: boundary.TVDSS_BOT_TOTAL,
      TVDSS_TOP_LOCAL: boundary.TVDSS_TOP_LOCAL,
      TVDSS_BOT_LOCAL: boundary.TVDSS_BOT_LOCAL
    }));
    const result = await window.petrel.run('save-section-boundaries', {
      path,
      outputPath,
      columnMapping: currentColumnMapping(),
      records
    });
    const selected = $('section-well').value;
    if (selected) state.sectionSavedWells[selected] = true;
    fillSectionWells(state.sectionTrajectories);
    saveState();
    setReady(`Saved boundaries: ${result.rowsUpdated || 0} rows`);
    appendLog(`Section boundaries saved: ${result.outputPath || outputPath}`);
  } catch (error) {
    fail(error);
  }
}

function sectionBoundaryOutputPath(path) {
  const dir = dirname(path);
  const name = stripExtension(basename(path));
  const filename = name ? `${name}_boundaries.xlsx` : 'frac_list_boundaries.xlsx';
  return dir ? joinPath(dir, filename) : filename;
}

function drawPolyline(ctx, points, color, width, alpha) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.globalAlpha = alpha;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index += 1) {
    ctx.lineTo(points[index].x, points[index].y);
  }
  ctx.stroke();
  ctx.restore();
}

function sectionMeshToScreen(x, y, frame, mesh) {
  const xSpan = mesh.xMax - mesh.xMin || 1;
  const ySpan = mesh.yMax - mesh.yMin || 1;
  return {
    x: frame.left + ((x - mesh.xMin) / xSpan) * frame.width,
    y: frame.top + ((y - mesh.yMin) / ySpan) * frame.height
  };
}

function showSectionMeshTooltip(event, canvas, tooltip, mesh, common) {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = findSectionMeshQuad(mesh, x, y);
  if (!hit) {
    tooltip.hidden = true;
    return;
  }
  tooltip.hidden = false;
  tooltip.innerHTML = `
    <b>K ${hit.k}</b><br>
    ${escapeHtml(sectionXAxisTitle(common.axis))}: ${formatAxisTick((hit.points[0].x + hit.points[1].x) / 2)}<br>
    TVD: ${formatAxisTick((hit.points[0].y + hit.points[2].y) / 2)}<br>
    Value: ${formatAxisTick(hit.value)}
  `;
  tooltip.style.left = `${Math.min(rect.width - 210, x + 14)}px`;
  tooltip.style.top = `${Math.max(8, y - 58)}px`;
}

function findSectionMeshQuad(mesh, x, y) {
  for (let index = mesh.screenQuads.length - 1; index >= 0; index -= 1) {
    const candidate = mesh.screenQuads[index];
    if (x < candidate.bbox.minX || x > candidate.bbox.maxX || y < candidate.bbox.minY || y > candidate.bbox.maxY) continue;
    if (pointInPolygon(x, y, candidate.points)) return candidate.quad;
  }
  return null;
}

function polygonBBox(points) {
  const xRange = numericRange(points.map(point => point.x));
  const yRange = numericRange(points.map(point => point.y));
  return {
    minX: xRange.min,
    maxX: xRange.max,
    minY: yRange.min,
    maxY: yRange.max
  };
}

function pointInPolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
    const xi = points[i].x;
    const yi = points[i].y;
    const xj = points[j].x;
    const yj = points[j].y;
    const intersects = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

function sectionTicks(minValue, maxValue, count) {
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || minValue === maxValue) return [minValue || 0];
  const ticks = [];
  const step = niceTickStep((maxValue - minValue) / Math.max(1, count - 1));
  const start = Math.ceil(minValue / step) * step;
  for (let value = start; value <= maxValue + Math.abs(step) * 1e-9; value += step) {
    ticks.push(value);
  }
  return ticks;
}

function niceTickStep(rawStep) {
  if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
  const exponent = Math.floor(Math.log10(rawStep));
  const magnitude = Math.pow(10, exponent);
  const normalized = rawStep / magnitude;
  if (normalized <= 1) return magnitude;
  if (normalized <= 2) return 2 * magnitude;
  if (normalized <= 5) return 5 * magnitude;
  return 10 * magnitude;
}

function formatAxisTick(value) {
  if (!Number.isFinite(value)) return '';
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 10) return value.toFixed(1).replace(/\.0$/, '');
  return value.toFixed(4).replace(/\.?0+$/, '');
}

function sectionCurtainTraces(common, result) {
  const grid = buildSectionCurtainGrid(common.validRows, common.axis, common.depthMin, common.depthMax);
  return [
    sectionRasterTrace(grid, common.valueMin, common.valueMax),
    sectionHoverHeatmapTrace(grid, common, result)
  ];
}

function sectionRasterTrace(grid, valueMin, valueMax) {
  const width = Math.max(1, grid.x.length);
  const height = Math.max(1, grid.y.length);
  const dx = width > 1 ? (grid.x[width - 1] - grid.x[0]) / (width - 1) : 1;
  const dy = height > 1 ? (grid.y[height - 1] - grid.y[0]) / (height - 1) : 1;
  return {
    type: 'image',
    z: sectionRgbaImage(grid.z, valueMin, valueMax),
    x0: grid.x[0],
    y0: grid.y[0],
    dx: Number.isFinite(dx) && dx > 0 ? dx : 1,
    dy: Number.isFinite(dy) && dy > 0 ? dy : 1,
    colormodel: 'rgba256',
    hoverinfo: 'skip'
  };
}

function sectionHoverHeatmapTrace(grid, common, result) {
  return {
    type: 'heatmap',
    x: grid.x,
    y: grid.y,
    z: grid.z,
    colorscale: 'Viridis',
    zmin: common.valueMin,
    zmax: common.valueMax,
    opacity: 0,
    connectgaps: true,
    colorbar: { title: result.property_title || 'Value', thickness: 14 },
    hovertemplate: `${sectionXAxisTitle(common.axis)}: %{x:.2f}<br>Depth: %{y:.2f}<br>Value: %{z}<extra></extra>`
  };
}

function sectionRgbaImage(matrix, valueMin, valueMax) {
  const span = valueMax - valueMin;
  return matrix.map(row => row.map(value => {
    if (!Number.isFinite(value) || !Number.isFinite(span) || span <= 0) return [255, 255, 255, 0];
    return viridisColor((value - valueMin) / span);
  }));
}

function viridisColor(value) {
  const stops = [
    [0.000, 68, 1, 84],
    [0.130, 71, 44, 122],
    [0.250, 59, 82, 139],
    [0.380, 44, 113, 142],
    [0.500, 33, 145, 140],
    [0.630, 39, 173, 129],
    [0.750, 92, 200, 99],
    [0.880, 170, 220, 50],
    [1.000, 253, 231, 37]
  ];
  const t = Math.max(0, Math.min(1, value));
  for (let index = 1; index < stops.length; index += 1) {
    const right = stops[index];
    const left = stops[index - 1];
    if (t <= right[0]) {
      const fraction = (t - left[0]) / (right[0] - left[0]);
      return [
        Math.round(left[1] + (right[1] - left[1]) * fraction),
        Math.round(left[2] + (right[2] - left[2]) * fraction),
        Math.round(left[3] + (right[3] - left[3]) * fraction),
        255
      ];
    }
  }
  return [253, 231, 37, 255];
}

function sectionLayout(result, axis, depthMin, depthMax, xMin, xMax) {
  return {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    margin: { l: 78, r: 72, t: 44, b: 64 },
    hovermode: 'closest',
    xaxis: {
      title: sectionXAxisTitle(axis),
      range: Number.isFinite(xMin) && Number.isFinite(xMax) && xMax > xMin ? [xMin, xMax] : undefined,
      gridcolor: '#e3e8ef',
      zeroline: false
    },
    yaxis: {
      title: 'TVD',
      range: [depthMax, depthMin],
      gridcolor: '#e3e8ef',
      zeroline: false
    },
    title: {
      text: `${escapeHtml(result.well_name || '')} | ${escapeHtml(result.property_title || '')}`,
      font: { size: 14 }
    }
  };
}

function buildSectionCurtainGrid(rows, axis, depthMin, depthMax) {
  const stations = [];
  const byStation = new Map();
  rows.forEach(row => {
    const station = Number(row.station_index);
    const x = numericCell(row[axis]);
    const depth = numericCell(row.tvd_center);
    const value = numericCell(row.value);
    if (!Number.isFinite(station) || !Number.isFinite(x) || !Number.isFinite(depth) || !Number.isFinite(value)) return;
    if (!byStation.has(station)) {
      byStation.set(station, { x, rows: [] });
      stations.push(station);
    }
    byStation.get(station).rows.push({ depth, value });
  });
  stations.sort((a, b) => {
    const ax = byStation.get(a).x;
    const bx = byStation.get(b).x;
    return ax - bx;
  });
  byStation.forEach(station => {
    station.rows.sort((a, b) => a.depth - b.depth);
  });
  const x = monotonicAxisValues(stations.map(station => byStation.get(station).x));
  const y = sectionDepthGrid(rows, depthMin, depthMax);
  const z = y.map(depth => stations.map(station => interpolateStationValue(byStation.get(station).rows, depth)));
  return { x, y, z };
}

function monotonicAxisValues(values) {
  if (!values.length) return values;
  const finite = values.filter(Number.isFinite);
  const range = numericRange(finite);
  const span = finite.length ? range.max - range.min : 1;
  const epsilon = Math.max(1e-6, Math.max(1, span) * 1e-9);
  const result = values.slice();
  for (let index = 1; index < result.length; index += 1) {
    if (!Number.isFinite(result[index])) continue;
    if (!Number.isFinite(result[index - 1])) continue;
    if (result[index] <= result[index - 1]) {
      result[index] = result[index - 1] + epsilon;
    }
  }
  return result;
}

function sectionDepthGrid(rows, depthMin, depthMax) {
  const heights = rows.map(row => Math.abs(numericCell(row.tvd_base) - numericCell(row.tvd_top))).filter(value => Number.isFinite(value) && value > 0);
  const medianHeight = median(heights);
  const range = Math.max(1, depthMax - depthMin);
  const targetStep = Number.isFinite(medianHeight) ? Math.max(0.2, medianHeight) : range / 400;
  const binCount = Math.max(40, Math.min(700, Math.ceil(range / targetStep)));
  const step = range / binCount;
  const y = [];
  for (let index = 0; index <= binCount; index += 1) {
    y.push(depthMin + step * index);
  }
  return y;
}

function interpolateStationValue(samples, depth) {
  if (!samples || !samples.length) return null;
  if (depth < samples[0].depth || depth > samples[samples.length - 1].depth) return null;
  let previous = samples[0];
  for (let index = 1; index < samples.length; index += 1) {
    const current = samples[index];
    if (depth <= current.depth) {
      if (current.depth === previous.depth) return current.value;
      const fraction = (depth - previous.depth) / (current.depth - previous.depth);
      return previous.value + (current.value - previous.value) * fraction;
    }
    previous = current;
  }
  return samples[samples.length - 1].value;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return NaN;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function sectionXAxisMode() {
  const value = $('section-axis').value;
  if (value === 'md' || value === 'distance' || value === 'horizontal_distance') return value;
  return 'horizontal_distance';
}

function sectionXAxisTitle(axis) {
  if (axis === 'md') return 'MD, m';
  if (axis === 'distance') return '3D distance along well, m';
  return 'Horizontal distance along trajectory projection, m';
}

function handleBackendEvent(message) {
  if (message.event === 'log' && message.message) appendLog(message.message);
  if (message.event === 'progress') {
    if (message.command === 'extract') setProgress('extraction-progress', message.value || 0);
    if (message.command === 'metrics') setProgress('metrics-progress', message.value || 0);
    if (message.command === 'model-section') setProgress('section-progress', message.value || 0);
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

function fillSelectOptions(id, options, selected) {
  const select = $(id);
  if (!select) return;
  select.innerHTML = '<option value=""></option>' + options.map(option => {
    const selectedAttr = selected && option.value === selected ? 'selected' : '';
    return `<option value="${escapeHtml(option.value)}" ${selectedAttr}>${escapeHtml(option.label)}</option>`;
  }).join('');
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
  state.extractionSelectedProperties = currentExtractionSelectedProperties();
  state.columnMapping = currentColumnMapping();
  const data = {
    models: state.models,
    sleevesPath: $('sleeves-path').value,
    selectedWells: state.selectedWells,
    extractionSelectedProperties: state.extractionSelectedProperties,
    columnMapping: state.columnMapping,
    hasSavedWellSelection: state.hasSavedWellSelection,
    outputPath: $('output-path').value,
    skipInactive: $('skip-inactive').checked,
    writeDiagnostics: $('write-diagnostics').checked,
    parallelWorkers: $('parallel-workers').value,
    metricsExtracted: $('metrics-extracted').value,
    metricsIntervals: $('metrics-intervals').value,
    metricsOutput: $('metrics-output').value,
    curvePath: $('curve-path').value,
    sectionWellNameMap: state.sectionWellNameMap,
    sectionSavedWells: state.sectionSavedWells,
    sectionStep: $('section-step').value,
    sectionMaxStations: $('section-max-stations').value,
    sectionAxis: $('section-axis').value,
    sectionSkipInactive: $('section-skip-inactive').checked,
    sectionShowBoundaries: $('section-show-boundaries').checked
  };
  localStorage.setItem('petrelhacker.state', JSON.stringify(data));
}

function restoreState() {
  try {
    const data = JSON.parse(localStorage.getItem('petrelhacker.state') || '{}');
    if (data.models) state.models = data.models;
    if (Array.isArray(data.selectedWells)) state.selectedWells = data.selectedWells;
    if (data.extractionSelectedProperties && typeof data.extractionSelectedProperties === 'object') {
      state.extractionSelectedProperties = data.extractionSelectedProperties;
    }
    if (data.columnMapping && typeof data.columnMapping === 'object') state.columnMapping = data.columnMapping;
    if (data.sectionWellNameMap && typeof data.sectionWellNameMap === 'object') state.sectionWellNameMap = data.sectionWellNameMap;
    if (data.sectionSavedWells && typeof data.sectionSavedWells === 'object') state.sectionSavedWells = data.sectionSavedWells;
    state.hasSavedWellSelection = Boolean(data.hasSavedWellSelection);
    renderModels();
    $('sleeves-path').value = data.sleevesPath || '';
    $('output-path').value = basename(data.outputPath || '');
    if (data.skipInactive !== undefined) $('skip-inactive').checked = Boolean(data.skipInactive);
    if (data.writeDiagnostics !== undefined) $('write-diagnostics').checked = Boolean(data.writeDiagnostics);
    if (data.parallelWorkers) $('parallel-workers').value = data.parallelWorkers;
    $('metrics-extracted').value = data.metricsExtracted || '';
    $('metrics-intervals').value = data.metricsIntervals || '';
    $('metrics-output').value = basename(data.metricsOutput || '');
    $('curve-path').value = data.curvePath || '';
    if (data.sectionStep) $('section-step').value = data.sectionStep;
    if (data.sectionMaxStations) $('section-max-stations').value = data.sectionMaxStations;
    if (data.sectionAxis) $('section-axis').value = data.sectionAxis;
    if (data.sectionSkipInactive !== undefined) $('section-skip-inactive').checked = Boolean(data.sectionSkipInactive);
    if (data.sectionShowBoundaries !== undefined) $('section-show-boundaries').checked = Boolean(data.sectionShowBoundaries);
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

function numericRange(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values || []) {
    const number = Number(value);
    if (!Number.isFinite(number)) continue;
    if (number < min) min = number;
    if (number > max) max = number;
  }
  return {
    min: min === Infinity ? NaN : min,
    max: max === -Infinity ? NaN : max
  };
}

function numericInput(id) {
  const element = $(id);
  if (!element || element.value === '') return NaN;
  const number = Number(element.value);
  return Number.isFinite(number) ? number : NaN;
}

document.addEventListener('DOMContentLoaded', init);
