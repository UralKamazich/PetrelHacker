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
  curveSettings: {},
  sectionTrajectories: [],
  sectionResult: null,
  sectionRows: [],
  sectionMesh: null,
  sectionViewXRange: null,
  sectionWellNameMap: {},
  sectionUseExtractionSelection: false,
  sectionBoundaries: [],
  sectionBoundaryPath: '',
  sectionSceneSettings: {},
  currentSectionSceneKey: '',
  currentSectionContext: null,
  currentSectionPayload: null,
  sectionSavedWells: {},
  sectionCachedWells: {},
  sectionBoundaryFileName: '',
  sectionBoundaryDrag: null,
  sectionAxisDrag: null,
  sectionAutoDrawTimer: null,
  sectionSelectedHorizons: {},
  wellAssignments: {},
  wellTrajectoryAnalyses: {}
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
  updateWorkflowSummaries();
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
  $('load-well-matches').addEventListener('click', () => loadWellMatchingJson().catch(fail));
  $('save-well-matches').addEventListener('click', () => saveWellMatchingJson().catch(fail));
  $('run-extraction').addEventListener('click', runExtraction);
  $('browse-sleeves').addEventListener('click', browseSleeves);
  $('browse-output').addEventListener('click', browseExtractionOutput);
  ['output-path', 'skip-inactive', 'write-diagnostics', 'parallel-workers'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
  $('select-all-wells').addEventListener('click', () => setAllWells(true));
  $('clear-wells').addEventListener('click', () => setAllWells(false));
  $('calculate-selected-xy').addEventListener('click', calculateSelectedWellCoordinates);
  $('overwrite-sleeve-xy').addEventListener('change', saveState);
  $('well-search').addEventListener('input', renderWells);
  $('select-all-properties').addEventListener('click', () => setAllProperties(true));
  $('clear-properties').addEventListener('click', () => setAllProperties(false));
  $('browse-metrics-extracted').addEventListener('click', async () => setPath('metrics-extracted', await pickTable('metrics-extracted')));
  $('browse-metrics-intervals').addEventListener('click', browseMetricsIntervals);
  $('browse-metrics-output').addEventListener('click', browseMetricsOutput);
  $('load-metrics-table').addEventListener('click', loadMetricsTable);
  $('run-metrics').addEventListener('click', runMetrics);
  $('browse-curve-path').addEventListener('click', async () => setPath('curve-path', await pickTable('curve-table')));
  $('load-curve-table').addEventListener('click', loadCurveTable);
  $('draw-curves').addEventListener('click', drawCurves);
  ['section-property', 'section-well', 'section-step', 'section-skip-inactive'].forEach(id => {
    $(id).addEventListener('change', clearSectionAutoBounds);
  });
  $('section-property').addEventListener('change', renderSectionHorizons);
  ['section-property', 'section-well', 'section-step', 'section-axis', 'section-skip-inactive'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
  $('section-well').addEventListener('change', scheduleCachedSectionAutoDraw);
  ['section-boundary-gap', 'section-min-layer'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
  $('section-boundary-file').addEventListener('change', () => {
    state.sectionBoundaryFileName = $('section-boundary-file').value.trim();
    state.sectionBoundaryPath = sectionBoundaryOutputPathFromInput();
    state.currentSectionSceneKey = currentSectionSceneKeyForPath(state.sectionBoundaryPath);
    saveState();
  });
  ['section-axis', 'section-depth-min', 'section-depth-max', 'section-value-min', 'section-value-max'].forEach(id => {
    $(id).addEventListener('change', () => {
      if (id === 'section-axis') state.sectionViewXRange = null;
      if (state.sectionResult) paintSection(state.sectionResult);
    });
  });
  $('load-section-from-extraction').addEventListener('click', loadSectionFromExtraction);
  $('load-section-wells').addEventListener('click', loadSectionWells);
  $('draw-section').addEventListener('click', drawSection);
  $('section-auto-boundaries').addEventListener('click', autoPlaceSectionBoundaries);
  $('section-save-boundaries').addEventListener('click', saveSectionBoundaries);
  $('section-clear-cache').addEventListener('click', clearSectionCache);
  $('section-show-boundaries').addEventListener('change', () => {
    if (state.sectionMesh) redrawCurrentSectionMesh();
    saveState();
  });
  $('section-barrier-thickness').addEventListener('change', saveState);
  $('clear-log').addEventListener('click', () => $('log-view').textContent = '');
  ['curve-well', 'curve-port'].forEach(id => {
    $(id).addEventListener('change', () => {
      saveState();
      drawCurves();
    });
  });
  ['curve-depth-mode', 'curve-depth-min', 'curve-depth-max'].forEach(id => {
    $(id).addEventListener('change', saveState);
  });
  window.addEventListener('resize', () => {
    if (state.sectionResult) paintSection(state.sectionResult);
  });
  window.addEventListener('mouseup', stopSectionDrag);
}

function renderModels() {
  const root = $('model-stack');
  root.innerHTML = '';
  state.models.forEach((model, index) => {
    const grids = Array.isArray(model.internalGrids) ? model.internalGrids : [];
    const gridSelect = grids.length > 1 ? `
      <label class="field model-grid-field">
        <span>Petrel model</span>
        <select data-model-grid="${index}">
          <option value="" ${model.gridUuid ? '' : 'selected'}>Select Petrel model</option>
          ${grids.map(grid => `<option value="${escapeHtml(grid.uuid)}" ${grid.uuid === model.gridUuid ? 'selected' : ''}>${escapeHtml(gridLabel(grid))}</option>`).join('')}
        </select>
      </label>
    ` : '';
    const sourceNote = model.sourceKind === 'petrel-project'
      ? `<div class="model-source-note">${grids.length} Petrel model(s), ${Number(model.propertyCount || 0)} propert${Number(model.propertyCount || 0) === 1 ? 'y' : 'ies'}</div>`
      : '';
    const card = document.createElement('div');
    card.className = `model-card${gridSelect ? ' has-grid-select' : ''}`;
    card.innerHTML = `
      <div class="model-badge">${model.label}</div>
      <div class="model-path-stack">
        <label class="field"><span>Model file / folder</span><input type="text" value="${escapeHtml(model.path)}" data-model-path="${index}" placeholder="Select .pet, .epc, Rescue .bin, or folder"></label>
        ${gridSelect}
        ${sourceNote}
      </div>
      <label class="field"><span>Depth shift, m</span><input type="number" step="0.1" value="${model.depthOffset}" data-model-offset="${index}"></label>
      <button class="icon-button" data-model-browse="${index}" type="button" title="Select model">...</button>
      <button class="icon-button model-clear-button" data-model-clear="${index}" type="button" title="Clear model" aria-label="Clear ${escapeHtml(model.label)}">x</button>
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
  root.querySelectorAll('[data-model-grid]').forEach(select => {
    select.addEventListener('change', () => {
      state.models[Number(select.dataset.modelGrid)].gridUuid = select.value;
      saveState();
    });
  });
  root.querySelectorAll('[data-model-browse]').forEach(button => {
    button.addEventListener('click', async () => {
      const index = Number(button.dataset.modelBrowse);
      const selected = await window.petrel.openModel({ dialogKey: 'models' });
      if (!selected) return;
      state.models[index].path = selected;
      await inspectModelSource(index);
      renderModels();
      saveState();
    });
  });
  root.querySelectorAll('[data-model-clear]').forEach(button => {
    button.addEventListener('click', () => {
      clearModelSelection(Number(button.dataset.modelClear)).catch(fail);
    });
  });
}

async function clearModelSelection(index) {
  const model = state.models[index];
  if (!model) return;
  const oldPath = model.path;
  const removed = state.loadedModels.find(item => item.label === model.label) || null;
  model.path = '';
  model.depthOffset = 0;
  model.internalGrids = [];
  model.sourceKind = '';
  model.propertyCount = 0;
  model.gridUuid = '';
  state.loadedModels = state.loadedModels.filter(item => item.label !== model.label);

  const removedTrajectoryNames = new Set((removed && removed.trajectories || []).map(sectionTrajectoryName));
  Object.keys(state.sectionWellNameMap || {}).forEach(name => {
    if (removedTrajectoryNames.has(name)) delete state.sectionWellNameMap[name];
  });
  Object.keys(state.wellAssignments || {}).forEach(key => {
    if (state.wellAssignments[key].modelLabel === model.label) {
      delete state.wellAssignments[key];
      delete state.wellTrajectoryAnalyses[key];
    }
  });

  if (oldPath && state.currentSectionContext && state.currentSectionContext.modelPath === oldPath) {
    state.sectionResult = null;
    state.sectionRows = [];
    state.sectionMesh = null;
    state.sectionBoundaries = [];
    state.currentSectionContext = null;
    state.currentSectionPayload = null;
    $('section-plot').innerHTML = '';
    clearSectionCellInspector($('section-cell-inspector'));
  }

  state.sectionTrajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
  renderModels();
  renderProperties();
  renderSectionModels();
  fillSectionWells(state.sectionTrajectories);
  renderWells();
  updateWorkflowSummaries();
  saveState();
  setReady(`${model.label} cleared`);
}

async function inspectModelSource(index) {
  const model = state.models[index];
  model.internalGrids = [];
  model.sourceKind = '';
  model.propertyCount = 0;
  model.gridUuid = '';
  try {
    const info = await window.petrel.run('model-source-info', { path: model.path });
    model.path = info.path || model.path;
    model.sourceKind = info.kind || '';
    model.internalGrids = Array.isArray(info.grids) ? info.grids : [];
    model.propertyCount = Number(info.propertyCount || 0);
    if (model.internalGrids.length === 1) {
      model.gridUuid = model.internalGrids[0].uuid || '';
    }
  } catch (error) {
    appendLog(`Model source inspect failed: ${error.message}`);
  }
}

function gridLabel(grid) {
  const title = grid.title || grid.uuid || 'Petrel model';
  const type = grid.gridType || grid.grid_type || '';
  const shape = [grid.ni, grid.nj, grid.nk].every(value => value)
    ? ` ${grid.ni} x ${grid.nj} x ${grid.nk}`
    : '';
  const properties = Array.isArray(grid.propertyNames) && grid.propertyNames.length
    ? ` - ${grid.propertyNames.join(', ')}`
    : '';
  return `${title}${type ? ` - ${type}` : ''}${shape}${properties}`;
}

async function loadModels() {
  setBusy('Loading models', 'Reading properties, wells, and named surfaces');
  try {
    const result = await window.petrel.run('load-models', { models: requestModels() });
    state.loadedModels = result.models || [];
    state.loadedModels.forEach(loaded => {
      const model = state.models.find(item => item.label === loaded.label);
      if (model) {
        if (loaded.path) model.path = loaded.path;
        loaded.gridUuid = loaded.gridUuid || model.gridUuid || '';
      }
    });
    renderModels();
    renderProperties();
    renderSectionModels();
    state.sectionTrajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
    ensureWellAssignments();
    await refreshWellTrajectoryAnalyses();
    await refreshSectionSavedWellsFromBoundaryFile();
    fillSectionWells(state.sectionTrajectories);
    renderWells();
    updateWorkflowSummaries();
    const surfaceCount = sectionHorizonOptions().length;
    $('section-summary').textContent = `Wells: ${state.sectionTrajectories.length}, surfaces: ${surfaceCount}`;
    saveState();
    setReady(`Loaded ${state.loadedModels.length} model(s), ${state.sectionTrajectories.length} wells, ${surfaceCount} surfaces`);
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
    ensureWellAssignments();
    await refreshWellTrajectoryAnalyses();
    renderMapping(result);
    renderWells();
    if (!$('output-path').value.trim()) {
      const suggested = await window.petrel.run('suggest-output', { sleevesPath: path });
      $('output-path').value = basename(suggested.outputPath || '');
    }
    applyMetricsDefaultsFromSleeves(path);
    updateSectionBoundaryFileDefault();
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
    updateSectionBoundaryFileDefault();
    saveState();
    setReady(`Sleeves headers: ${result.columns.length} columns`);
  } catch (error) {
    fail(error);
  }
}

async function browseSleeves() {
  const selected = await pickTable('sleeves');
  if (!selected) return;
  const previous = $('sleeves-path').value.trim();
  $('sleeves-path').value = selected;
  if (selected !== previous) {
    clearSleevesDependentState();
  }
  $('sleeves-name').value = basename(selected);
  await loadSleevesHeaders();
}

function clearSleevesDependentState() {
  state.sleeves = null;
  state.sectionBoundaryPath = '';
  state.sectionBoundaryFileName = '';
  state.currentSectionSceneKey = '';
  state.currentSectionContext = null;
  state.currentSectionPayload = null;
  $('section-boundary-file').value = '';
  $('sleeves-name').value = '';
  renderEmptyMapping();
  $('well-list').innerHTML = '';
  $('well-summary').textContent = 'No sleeves loaded';
  $('output-path').value = '';
  state.wellTrajectoryAnalyses = {};
  updateWorkflowSummaries();
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
    .slice()
    .sort((left, right) => String(left.name).localeCompare(String(right.name), undefined, { numeric: true, sensitivity: 'base' }))
    .filter(well => !query || well.name.toLowerCase().indexOf(query) >= 0)
    .forEach(well => {
    const row = document.createElement('div');
    row.className = 'well-item';
    const checked = state.selectedWells.indexOf(well.name) >= 0 ? 'checked' : '';
    const assignment = wellAssignment(well.name);
    const modelOptions = ['<option value="">-</option>'].concat(state.loadedModels.map(model => (
      `<option value="${escapeHtml(model.label)}" ${assignment && assignment.modelLabel === model.label ? 'selected' : ''}>${escapeHtml(model.label)}</option>`
    ))).join('');
    const trajectories = assignment ? wellModelTrajectories(assignment.modelLabel) : [];
    const trajectoryOptions = ['<option value="">-</option>'].concat(trajectories.map(trajectory => (
      `<option value="${escapeHtml(trajectory.uuid)}" ${assignment && assignment.trajectoryUuid === trajectory.uuid ? 'selected' : ''}>${escapeHtml(sectionTrajectoryName(trajectory))}</option>`
    ))).join('');
    const analysis = assignment ? state.wellTrajectoryAnalyses[wellAssignmentKey(well.name)] : null;
    const xyValid = Number(well.validXY || 0);
    const xyTotal = xyValid + Number(well.missingXY || 0);
    row.innerHTML = `
      <input type="checkbox" ${checked} data-well="${escapeHtml(well.name)}">
      <strong>${escapeHtml(well.name)}</strong>
      <span class="muted">${well.count}</span>
      <span class="well-xy-state${xyValid < xyTotal ? ' incomplete' : ''}">${xyValid} / ${xyTotal}</span>
      <select data-well-model="${escapeHtml(well.name)}">${modelOptions}</select>
      <select data-well-trajectory="${escapeHtml(well.name)}" ${assignment && assignment.modelLabel ? '' : 'disabled'}>${trajectoryOptions}</select>
      <span class="well-trajectory-metric">${formatWellMetric(analysis && analysis.maxAngle, '°')}</span>
      <span class="well-trajectory-metric">${formatWellMetric(analysis && analysis.last500Azimuth, '°')}</span>
      <span class="well-trajectory-metric">${formatWellMetric(analysis && analysis.bottomMd, ' m')}</span>
    `;
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
  root.querySelectorAll('[data-well-model]').forEach(select => {
    select.addEventListener('change', () => {
      const wellName = select.dataset.wellModel;
      const modelLabel = select.value;
      const exact = wellModelTrajectories(modelLabel).find(item => normalizeLookupTextSafe(sectionTrajectoryName(item)) === normalizeLookupTextSafe(wellName));
      setWellAssignment(wellName, modelLabel, exact ? exact.uuid : '');
      renderWells();
      saveState();
      if (exact) refreshWellTrajectoryAnalyses([wellName]).catch(fail);
    });
  });
  root.querySelectorAll('[data-well-trajectory]').forEach(select => {
    select.addEventListener('change', () => {
      const wellName = select.dataset.wellTrajectory;
      const assignment = wellAssignment(wellName);
      setWellAssignment(wellName, assignment ? assignment.modelLabel : '', select.value);
      renderWells();
      saveState();
      refreshWellTrajectoryAnalyses([wellName]).catch(fail);
    });
  });
  updateWorkflowSummaries();
}

function wellTrajectoryMatch(fracWell) {
  const assignment = wellAssignment(fracWell);
  if (assignment && assignment.trajectoryName) return assignment.trajectoryName;
  const explicit = Object.entries(state.sectionWellNameMap || {})
    .find(([_modelName, mappedFrac]) => normalizeLookupTextSafe(mappedFrac) === normalizeLookupTextSafe(fracWell));
  if (explicit) return explicit[0];
  const exact = (state.sectionTrajectories || [])
    .find(item => normalizeLookupTextSafe(sectionTrajectoryName(item)) === normalizeLookupTextSafe(fracWell));
  return exact ? sectionTrajectoryName(exact) : '';
}

function wellAssignmentKey(wellName) {
  return normalizeLookupTextSafe(wellName);
}

function wellAssignment(wellName) {
  return state.wellAssignments[wellAssignmentKey(wellName)] || null;
}

function wellModelTrajectories(modelLabel) {
  const model = state.loadedModels.find(item => item.label === modelLabel);
  return model
    ? deduplicateTrajectories(annotateSectionTrajectories(model.trajectories || [], model))
      .sort((left, right) => sectionTrajectoryName(left).localeCompare(sectionTrajectoryName(right), undefined, { numeric: true, sensitivity: 'base' }))
    : [];
}

function setWellAssignment(wellName, modelLabel, trajectoryUuid) {
  const key = wellAssignmentKey(wellName);
  if (!modelLabel) {
    delete state.wellAssignments[key];
    delete state.wellTrajectoryAnalyses[key];
    return;
  }
  const trajectory = wellModelTrajectories(modelLabel).find(item => item.uuid === trajectoryUuid) || null;
  state.wellAssignments[key] = {
    wellName,
    modelLabel,
    trajectoryUuid: trajectory ? trajectory.uuid : '',
    trajectoryName: trajectory ? sectionTrajectoryName(trajectory) : ''
  };
  Object.keys(state.sectionWellNameMap || {}).forEach(name => {
    if (normalizeLookupTextSafe(state.sectionWellNameMap[name]) === key) delete state.sectionWellNameMap[name];
  });
  if (trajectory) state.sectionWellNameMap[sectionTrajectoryName(trajectory)] = wellName;
  delete state.wellTrajectoryAnalyses[key];
}

function ensureWellAssignments() {
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  wells.forEach(well => {
    if (wellAssignment(well.name)) return;
    for (const model of state.loadedModels) {
      const trajectory = wellModelTrajectories(model.label)
        .find(item => normalizeLookupTextSafe(sectionTrajectoryName(item)) === normalizeLookupTextSafe(well.name));
      if (!trajectory) continue;
      setWellAssignment(well.name, model.label, trajectory.uuid);
      break;
    }
  });
}

async function refreshWellTrajectoryAnalyses(wellNames = null) {
  const names = wellNames || (state.sleeves ? (state.sleeves.wells || []).map(well => well.name) : []);
  const assignments = names.map(name => {
    const assignment = wellAssignment(name);
    const model = assignment && state.loadedModels.find(item => item.label === assignment.modelLabel);
    return assignment && model && assignment.trajectoryUuid ? {
      key: wellAssignmentKey(name),
      path: model.path,
      trajectoryUuid: assignment.trajectoryUuid
    } : null;
  }).filter(Boolean);
  if (!assignments.length) {
    renderWells();
    return;
  }
  const result = await window.petrel.run('trajectory-analysis', { assignments });
  (result.analyses || []).forEach(analysis => {
    state.wellTrajectoryAnalyses[analysis.key] = analysis;
  });
  renderWells();
}

function formatWellMetric(value, suffix) {
  const number = numericCell(value);
  return Number.isFinite(number) ? `${formatAxisTick(number)}${suffix}` : '-';
}

async function calculateSelectedWellCoordinates() {
  const sourcePath = $('sleeves-path').value.trim();
  if (!sourcePath) return fail(new Error('Load frac-list first.'));
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  const overwriteExisting = $('overwrite-sleeve-xy').checked;
  const selected = wells.filter(well => state.selectedWells.includes(well.name));
  if (!selected.length) return fail(new Error('Select at least one well.'));
  const targets = selected.filter(well => overwriteExisting || Number(well.missingXY || 0) > 0);
  if (!targets.length) return setAttention('The file already contains X/Y data for the selected ports.');
  const ready = targets.map(well => {
    const assignment = wellAssignment(well.name);
    const model = assignment && state.loadedModels.find(item => item.label === assignment.modelLabel);
    return assignment && assignment.trajectoryUuid && model ? { well, assignment, model } : null;
  }).filter(Boolean);
  if (!ready.length) return fail(new Error('Selected wells have no assigned trajectories.'));
  setBusy('Saving coordinates', `${ready.length} selected well(s) to ${basename(sourcePath)}`);
  try {
    let updated = 0;
    let outside = 0;
    for (const target of ready) {
      const result = await window.petrel.run('calculate-sleeve-coordinates', {
        path: sourcePath,
        outputPath: sourcePath,
        wellName: target.well.name,
        modelPath: target.model.path,
        trajectoryUuid: target.assignment.trajectoryUuid,
        columnMapping: currentColumnMapping(),
        overwriteExisting
      });
      updated += Number(result.rowsUpdated || 0);
      outside += Number(result.rowsOutsideTrajectory || 0);
    }
    state.columnMapping = { ...currentColumnMapping(), X: 'X', Y: 'Y' };
    await loadSleeves();
    setReady(`Saved X/Y: ${updated} ports in ${ready.length} well(s)`);
    if (targets.length > ready.length) appendLog(`Warning: ${targets.length - ready.length} selected well(s) were skipped because no trajectory is assigned.`);
    if (outside) appendLog(`Warning: ${outside} port(s) are outside their trajectory MD range.`);
  } catch (error) {
    fail(error);
  }
}

function updateWorkflowSummaries() {
  const wells = state.sleeves ? state.sleeves.wells || [] : [];
  const stats = state.sleeves && state.sleeves.coordinateStats ? state.sleeves.coordinateStats : null;
  const availableNames = new Set(wells.map(well => well.name));
  const selectedWellCount = state.selectedWells.filter(name => availableNames.has(name)).length;
  if ($('well-stat-rows')) $('well-stat-rows').textContent = String(state.sleeves ? Number(state.sleeves.rows || 0) : 0);
  if ($('well-stat-wells')) $('well-stat-wells').textContent = String(wells.length);
  if ($('well-stat-selected')) $('well-stat-selected').textContent = String(selectedWellCount);
  if ($('well-stat-coordinates')) {
    $('well-stat-coordinates').textContent = stats ? `${Number(stats.validXY || 0)} / ${Number((stats.validXY || 0) + (stats.missingXY || 0))}` : '-';
  }
  const selectedProperties = document.querySelectorAll('[data-property]:checked').length;
  const selectedSleeves = wells
    .filter(well => state.selectedWells.includes(well.name))
    .reduce((total, well) => total + Number(well.count || 0), 0);
  if ($('extraction-model-count')) $('extraction-model-count').textContent = String(state.loadedModels.length);
  if ($('extraction-property-count')) $('extraction-property-count').textContent = String(selectedProperties);
  if ($('extraction-well-count')) $('extraction-well-count').textContent = String(selectedWellCount);
  if ($('extraction-sleeve-count')) $('extraction-sleeve-count').textContent = String(selectedSleeves);
  if ($('extraction-source')) $('extraction-source').textContent = basename($('sleeves-path').value.trim()) || 'No frac-list loaded';
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
    renderWells();
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
  const rows = uniqueNames(fracWells)
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
  return deduplicateTrajectories(trajectories)
    .slice()
    .sort((left, right) => sectionTrajectoryName(left).localeCompare(sectionTrajectoryName(right), undefined, { numeric: true, sensitivity: 'base' }))
    .map(item => {
      const name = sectionTrajectoryName(item);
      return {
        value: name,
        label: name
      };
    });
}

function uniqueNames(values) {
  const result = [];
  const seen = new Set();
  for (const value of values || []) {
    const key = normalizeLookupTextSafe(value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}

function deduplicateTrajectories(trajectories) {
  const result = [];
  const indexByName = new Map();
  for (const trajectory of trajectories || []) {
    const key = normalizeLookupTextSafe(sectionTrajectoryName(trajectory)) || trajectory.uuid;
    if (!indexByName.has(key)) {
      indexByName.set(key, result.length);
      result.push(trajectory);
      continue;
    }
    const index = indexByName.get(key);
    if (Number(trajectory.point_count || 0) > Number(result[index].point_count || 0)) result[index] = trajectory;
  }
  return result;
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
  const path = await window.petrel.openFile({
    dialogKey: 'well-matching',
    filters: [{ name: 'Well matching JSON', extensions: ['json'] }, { name: 'All files', extensions: ['*'] }]
  });
  if (!path) return;
  const text = await window.petrel.readTextFile(path);
  const data = JSON.parse(text);
  const assignments = data.assignments;
  const mappings = data.mappings || data.sectionWellNameMap || (!assignments ? data : {});
  if ((!assignments || typeof assignments !== 'object' || Array.isArray(assignments))
      && (!mappings || typeof mappings !== 'object' || Array.isArray(mappings))) {
    throw new Error('Invalid well matching JSON.');
  }
  if (assignments && typeof assignments === 'object' && !Array.isArray(assignments)) {
    state.wellAssignments = Object.fromEntries(Object.entries(assignments).map(([key, value]) => [key, {
      wellName: String(value.wellName || ''),
      modelLabel: String(value.modelLabel || ''),
      trajectoryUuid: String(value.trajectoryUuid || ''),
      trajectoryName: String(value.trajectoryName || '')
    }]));
  }
  state.sectionWellNameMap = Object.fromEntries(Object.entries(mappings || {}).map(([modelWell, fracWell]) => [String(modelWell), String(fracWell)]));
  ensureWellAssignments();
  await refreshWellTrajectoryAnalyses();
  renderWells();
  saveState();
  setReady(`Loaded well matches: ${Object.keys(state.wellAssignments).length}`);
}

async function saveWellMatchingJson() {
  const path = await window.petrel.saveFile({
    dialogKey: 'well-matching',
    defaultPath: 'well_matching.json',
    filters: [{ name: 'Well matching JSON', extensions: ['json'] }]
  });
  if (!path) return;
  const payload = {
    version: 2,
    savedAt: new Date().toISOString(),
    assignments: state.wellAssignments || {},
    mappings: state.sectionWellNameMap || {}
  };
  await window.petrel.writeTextFile(path, JSON.stringify(payload, null, 2));
  setReady(`Saved well matches: ${Object.keys(payload.assignments).length}`);
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
      updateWorkflowSummaries();
      saveState();
    });
  });
  updateWorkflowSummaries();
}

function renderSectionModels() {
  renderSectionProperties();
}

function renderSectionProperties() {
  const selected = $('section-property').value;
  const options = sectionPropertyOptions();
  fillSelectOptions('section-property', options, options.some(option => option.value === selected) ? selected : (options[0] && options[0].value));
  renderSectionHorizons();
}

function renderSectionHorizons() {
  const field = $('section-horizon-field');
  const root = $('section-horizons');
  if (!field || !root) return;
  const options = sectionHorizonOptions();
  field.hidden = !options.length;
  root.innerHTML = '';
  if (!options.length) return;
  const key = sectionHorizonSelectionKey();
  const selected = new Set(state.sectionSelectedHorizons[key] || []);
  options.forEach(option => {
    const label = document.createElement('label');
    label.className = 'section-horizon-item';
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(option.value)}" ${selected.has(option.value) ? 'checked' : ''}><span>${escapeHtml(option.label)}</span>`;
    root.appendChild(label);
  });
  root.querySelectorAll('input').forEach(input => {
    input.addEventListener('change', () => {
      state.sectionSelectedHorizons[key] = Array.from(root.querySelectorAll('input:checked')).map(item => item.value);
      saveState();
      if (!state.sectionResult) return;
      const loaded = new Set((state.sectionResult.horizons || []).map(horizon => horizon.uuid));
      const missing = state.sectionSelectedHorizons[key].some(uuid => !loaded.has(uuid));
      if (missing) drawSection().catch(fail);
      else paintSection(state.sectionResult);
    });
  });
}

function sectionHorizonSelectionKey() {
  return 'all-models';
}

function sectionHorizonValue(model, horizon) {
  return `${model.label || ''}::${model.path || ''}::${model.gridUuid || horizon.grid_uuid || ''}::${horizon.uuid || ''}`;
}

function sectionHorizonOptions() {
  const options = [];
  const seen = new Set();
  for (const model of state.loadedModels || []) {
    for (const horizon of model.namedHorizons || []) {
      const key = normalizeLookupTextSafe(horizon.title) || sectionHorizonValue(model, horizon);
      if (seen.has(key)) continue;
      seen.add(key);
      options.push({
        value: sectionHorizonValue(model, horizon),
        label: horizon.title,
        model,
        horizon
      });
    }
  }
  return options;
}

function selectedSectionHorizonUuids() {
  return new Set(state.sectionSelectedHorizons[sectionHorizonSelectionKey()] || []);
}

function selectedSectionHorizonSources() {
  const selected = selectedSectionHorizonUuids();
  return sectionHorizonOptions()
    .filter(option => selected.has(option.value))
    .map(option => ({
      path: option.model.path,
      gridUuid: option.model.gridUuid || option.horizon.grid_uuid || '',
      horizonUuid: option.horizon.uuid,
      selectionUuid: option.value,
      sourceModel: option.model.label,
      depthOffset: Number(option.model.depthOffset || 0)
    }));
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
  updateWorkflowSummaries();
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
    const metricKeys = checkedValues('metric-key');
    if (!metricKeys.length) {
      throw new Error('Select at least one metric.');
    }
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
      metricKeys
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
    const saved = state.curveSettings || {};
    fillSelect('curve-well', wells, wells.includes(saved.well) ? saved.well : wells[0]);
    fillSelect('curve-port', ports, ports.includes(saved.port) ? saved.port : ports[0]);
    $('curve-depth-mode').value = saved.depthMode || 'common';
    renderCurveControls(true);
    await autoFitAndDrawCurves();
    applySavedCurveRanges();
    setReady(`Curve table: ${result.rows} rows`);
  } catch (error) {
    fail(error);
  }
}

function renderCurveControls(autoSelect) {
  const root = $('curve-controls');
  root.innerHTML = '';
  const columns = curveChannelColumns();
  const saved = state.curveSettings || {};
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
    const savedChannel = saved.channels && saved.channels[index - 1];
    const selected = savedChannel && columns.includes(savedChannel)
      ? savedChannel
      : (autoSelect ? columns[index - 1] : undefined);
    fillSelect(`curve-channel-${index}`, columns, selected);
    if (saved.mins && saved.mins[index - 1] !== undefined) $(`curve-min-${index}`).value = saved.mins[index - 1];
    if (saved.maxs && saved.maxs[index - 1] !== undefined) $(`curve-max-${index}`).value = saved.maxs[index - 1];
    if (saved.shifts && saved.shifts[index - 1] !== undefined) $(`curve-shift-${index}`).value = saved.shifts[index - 1];
  }
  root.querySelectorAll('select,input').forEach(element => element.addEventListener('change', saveState));
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
  applySavedCurveRanges();
  paintCurves(result.depthColumn, result.channelDepthColumns || {}, columns, result.rows || []);
}

function applySavedCurveRanges() {
  const saved = state.curveSettings || {};
  if (saved.depthMin !== undefined) $('curve-depth-min').value = saved.depthMin;
  if (saved.depthMax !== undefined) $('curve-depth-max').value = saved.depthMax;
  for (let index = 1; index <= 4; index += 1) {
    if (saved.mins && saved.mins[index - 1] !== undefined) $(`curve-min-${index}`).value = saved.mins[index - 1];
    if (saved.maxs && saved.maxs[index - 1] !== undefined) $(`curve-max-${index}`).value = saved.maxs[index - 1];
    if (saved.shifts && saved.shifts[index - 1] !== undefined) $(`curve-shift-${index}`).value = saved.shifts[index - 1];
  }
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
  const sleeveDepth = curveSleeveDepth(rows);
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
    shapes: [],
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
  if (Number.isFinite(sleeveDepth)) {
    layout.shapes.push({
      type: 'line',
      xref: 'paper',
      yref: 'y',
      x0: 0,
      x1: 1,
      y0: sleeveDepth,
      y1: sleeveDepth,
      line: { color: '#ef4444', width: 2, dash: 'dash' }
    });
    layout.annotations.push({
      text: `Port ${escapeHtml($('curve-port').value || '')}`,
      x: 1,
      y: sleeveDepth,
      xref: 'paper',
      yref: 'y',
      showarrow: false,
      xanchor: 'right',
      yanchor: 'bottom',
      font: { color: '#b91c1c', size: 11 },
      bgcolor: 'rgba(255,255,255,0.75)',
      borderpad: 2
    });
  }
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

function curveSleeveDepth(rows) {
  for (const row of rows || []) {
    const depth = numericCell(row.TVDSS_PORT);
    if (Number.isFinite(depth)) return depth;
  }
  for (const row of rows || []) {
    const depth = numericCell(row.Depth_KB_PORT);
    if (Number.isFinite(depth)) return depth;
  }
  return NaN;
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
  setBusy('Loading wells', 'Reading trajectories from all models');
  try {
    state.sectionUseExtractionSelection = false;
    renderSectionProperties();
    state.sectionTrajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
    await refreshSectionSavedWellsFromBoundaryFile();
    fillSectionWells(state.sectionTrajectories);
    $('section-summary').textContent = `Trajectories: ${state.sectionTrajectories.length}`;
    setReady(`Well trajectories: ${state.sectionTrajectories.length}`);
  } catch (error) {
    fail(error);
  }
}

async function loadSectionFromExtraction() {
  if (!state.loadedModels.length) return fail(new Error('Load models first.'));
  setBusy('Loading section context', 'Reading Wells selection');
  try {
    state.sectionUseExtractionSelection = true;
    renderSectionProperties();
    await ensureExtractionWellsLoaded();
    const trajectories = await loadSectionTrajectoriesFromModels(state.loadedModels);
    const extractionWells = sectionExtractionWellNames();
    state.sectionTrajectories = await resolveSectionTrajectoriesFromExtraction(trajectories, extractionWells);
    await refreshSectionSavedWellsFromBoundaryFile();
    fillSectionWells(state.sectionTrajectories);
    if (!extractionWells.length) {
      appendLog('Warning: no wells are selected on the Wells page; section well list is empty.');
    } else if (!state.sectionTrajectories.length) {
      appendLog('Warning: no model trajectories were matched to selected wells. Use Match wells on the Wells page.');
    }
    $('section-summary').textContent = `Selected wells: ${state.sectionTrajectories.length}`;
    setReady(`Selected well trajectories: ${state.sectionTrajectories.length}`);
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
  if (Array.isArray(model.trajectories)) {
    return annotateSectionTrajectories(model.trajectories, model);
  }
  const result = await window.petrel.run('well-trajectories', { path: model.path, includePoints: false });
  return annotateSectionTrajectories(result.trajectories || [], model);
}

async function loadSectionTrajectoriesFromModels(models) {
  const all = [];
  const indexByName = new Map();
  for (const model of models || []) {
    if (!model || !model.path) continue;
    try {
      for (const trajectory of await loadSectionTrajectories(model)) {
        const key = normalizeLookupTextSafe(sectionTrajectoryName(trajectory)) || `${trajectory.source_path || ''}::${trajectory.uuid || ''}`;
        if (!indexByName.has(key)) {
          indexByName.set(key, all.length);
          all.push(trajectory);
          continue;
        }
        const index = indexByName.get(key);
        if (Number(trajectory.point_count || 0) > Number(all[index].point_count || 0)) all[index] = trajectory;
      }
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
    let matched = findSectionTrajectoryForExtractionWell(trajectories, well, used);
    const assignment = wellAssignment(well);
    if (!matched && assignment && assignment.trajectoryUuid) {
      const model = state.loadedModels.find(item => item.label === assignment.modelLabel);
      const modelTrajectories = model ? await loadSectionTrajectories(model) : [];
      matched = modelTrajectories.find(item => item.uuid === assignment.trajectoryUuid) || null;
    }
    if (matched) {
      addSectionTrajectoryMatch(selected, used, matched, well);
    }
  }
  return selected;
}

function findSectionTrajectoryForExtractionWell(trajectories, well, used) {
  const key = normalizeLookupTextSafe(well);
  if (!key) return null;
  const assignment = wellAssignment(well);
  if (assignment && assignment.trajectoryUuid) {
    const assigned = trajectories.find(item => !used.has(item.uuid)
      && item.uuid === assignment.trajectoryUuid
      && (!assignment.modelLabel || item.source_model === assignment.modelLabel));
    if (assigned) return assigned;
  }
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
    const value = sectionTrajectoryValue(item);
    const points = state.sectionSavedWells && state.sectionSavedWells[value] ? ' [points]' : '';
    const section = state.sectionCachedWells && state.sectionCachedWells[value] ? ' [section]' : '';
    return {
      value,
      label: `${name}${source}${hasDuplicates ? ` (${item.point_count || '?'} pts)` : ''}${points}${section}`
    };
  });
  const selected = options.some(option => option.value === previous) ? previous : (options[0] && options[0].value);
  fillSelectOptions('section-well', options, selected);
}

async function refreshSectionSavedWellsFromBoundaryFile() {
  const path = currentSectionBoundaryPath();
  if (!path || !state.sectionTrajectories || !state.sectionTrajectories.length) return;
  try {
    const loaded = await window.petrel.run('load-section-boundaries', {
      path,
      columnMapping: currentColumnMapping()
    });
    const savedWellKeys = new Set((loaded.records || []).map(record => normalizeLookupTextSafe(record.well)).filter(Boolean));
    if (!savedWellKeys.size) return;
    for (const trajectory of state.sectionTrajectories) {
      if (sectionTrajectoryMatchesSavedWell(trajectory, savedWellKeys)) {
        state.sectionSavedWells[sectionTrajectoryValue(trajectory)] = true;
      }
    }
    saveState();
  } catch (error) {
    appendLog(`Warning: saved section markers were not loaded: ${error.message}`);
  }
}

function sectionTrajectoryMatchesSavedWell(trajectory, savedWellKeys) {
  const modelName = sectionTrajectoryName(trajectory);
  const mappedName = state.sectionWellNameMap && state.sectionWellNameMap[modelName] ? state.sectionWellNameMap[modelName] : '';
  return savedWellKeys.has(normalizeLookupTextSafe(modelName)) || savedWellKeys.has(normalizeLookupTextSafe(mappedName));
}

function sectionSelectedWellHasCachedSection() {
  const value = $('section-well').value;
  return Boolean(value && state.sectionCachedWells && state.sectionCachedWells[value]);
}

function scheduleCachedSectionAutoDraw() {
  if (state.sectionAutoDrawTimer) clearTimeout(state.sectionAutoDrawTimer);
  state.sectionAutoDrawTimer = setTimeout(() => {
    state.sectionAutoDrawTimer = null;
    if (!sectionSelectedWellHasCachedSection()) return;
    if (!$('section-property').value) return;
    appendLog('Cached section selected; loading section automatically.');
    drawSection({ cacheOnly: true }).catch(error => {
      const selected = $('section-well').value;
      if (selected && state.sectionCachedWells) {
        delete state.sectionCachedWells[selected];
        fillSectionWells(state.sectionTrajectories);
        saveState();
      }
      fail(error);
    });
  }, 120);
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
  state.sectionViewXRange = null;
}

async function drawSection(options = {}) {
  const cacheOnly = Boolean(options.cacheOnly);
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
  const configuredModel = state.models.find(item => item.label === model.label);
  const gridUuid = model.gridUuid
    || propertySelection.property.supporting_grid_uuid
    || (configuredModel && configuredModel.gridUuid)
    || '';
  await ensureSectionWellNameMapped(trajectoryValue);
  const sleeveMarkers = await loadSectionSleeveMarkers(sectionTrajectoryName(trajectory));
  setBusy('Drawing section', 'Sampling model along trajectory');
  try {
    const sectionPayload = {
      path: model.path,
      gridUuid,
      propertyUuid,
      trajectoryUuid,
      trajectoryPath: trajectory.source_path || model.path,
      sampleStep: Number($('section-step').value || 25),
      depthOffset: Number(model.depthOffset || 0),
      skipInactive: $('section-skip-inactive').checked,
      extraMds: sleeveMarkers.map(marker => numericCell(marker.md)).filter(Number.isFinite),
      horizonSources: selectedSectionHorizonSources(),
      cacheOnly
    };
    const result = unpackSectionResult(await window.petrel.run('model-section', sectionPayload));
    delete sectionPayload.cacheOnly;
    state.currentSectionPayload = sectionPayload;
    result.sleeveMarkers = sleeveMarkers;
    state.sectionResult = result;
    state.sectionRows = result.rows || [];
    state.sectionBoundaries = [];
    const boundaryPath = currentSectionBoundaryPath();
    state.currentSectionContext = {
      modelPath: model.path,
      propertyUuid,
      trajectorySourcePath: trajectory.source_path || model.path,
      trajectoryUuid
    };
    state.currentSectionSceneKey = currentSectionSceneKeyForPath(boundaryPath);
    applySectionSceneSettings(state.currentSectionSceneKey);
    paintSection(result);
    await restoreSectionBoundariesFromFile(boundaryPath, result, trajectory);
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

function currentSectionBoundaryPath() {
  updateSectionBoundaryFileDefault();
  return sectionBoundaryOutputPathFromInput();
}

function updateSectionBoundaryFileDefault() {
  const input = $('section-boundary-file');
  if (!input) return;
  const current = input.value.trim();
  if (current) return;
  const path = $('sleeves-path').value.trim();
  if (!path) return;
  const filename = basename(sectionBoundaryOutputPath(path));
  input.value = filename;
  state.sectionBoundaryFileName = filename;
  state.sectionBoundaryPath = sectionBoundaryOutputPathFromInput();
}

function sectionBoundaryOutputPathFromInput() {
  const raw = ($('section-boundary-file') ? $('section-boundary-file').value : '').trim() || state.sectionBoundaryFileName || '';
  if (!raw) return '';
  const filename = ensureExcelExtension(raw);
  state.sectionBoundaryFileName = filename;
  if ($('section-boundary-file') && $('section-boundary-file').value !== filename) $('section-boundary-file').value = filename;
  if (isAbsolutePath(filename)) return filename;
  const baseDir = dirname(state.sectionBoundaryPath || $('sleeves-path').value.trim());
  return baseDir ? joinPath(baseDir, filename) : filename;
}

function ensureExcelExtension(filename) {
  return /\.(xlsx|xlsm)$/i.test(filename) ? filename : `${filename}.xlsx`;
}

function sectionSceneKey(model, propertyUuid, trajectory, boundaryPath) {
  const parts = [
    model && model.path ? model.path : '',
    propertyUuid || '',
    trajectory && trajectory.source_path ? trajectory.source_path : '',
    trajectory && trajectory.uuid ? trajectory.uuid : '',
    boundaryPath || ''
  ];
  return parts.map(value => String(value || '').trim()).join('::');
}

function currentSectionSceneKeyForPath(boundaryPath) {
  const context = state.currentSectionContext || {};
  const parts = [
    context.modelPath || '',
    context.propertyUuid || '',
    context.trajectorySourcePath || '',
    context.trajectoryUuid || '',
    boundaryPath || ''
  ];
  return parts.map(value => String(value || '').trim()).join('::');
}

function currentSectionSceneSettings() {
  return {
    axis: $('section-axis').value,
    xRange: state.sectionViewXRange && Number.isFinite(state.sectionViewXRange.min) && Number.isFinite(state.sectionViewXRange.max)
      ? { min: state.sectionViewXRange.min, max: state.sectionViewXRange.max }
      : null,
    depthMin: $('section-depth-min').value,
    depthMax: $('section-depth-max').value,
    valueMin: $('section-value-min').value,
    valueMax: $('section-value-max').value,
    boundaryGap: $('section-boundary-gap').value,
    minLayer: $('section-min-layer').value,
    showBoundaries: $('section-show-boundaries').checked,
    barrierThickness: $('section-barrier-thickness').checked
  };
}

function saveCurrentSectionSceneSettings() {
  const key = state.currentSectionSceneKey;
  if (!key) return;
  state.sectionSceneSettings[key] = currentSectionSceneSettings();
}

function applySectionSceneSettings(key) {
  const settings = key && state.sectionSceneSettings ? state.sectionSceneSettings[key] : null;
  if (!settings) return false;
  if (settings.axis) $('section-axis').value = settings.axis;
  if (settings.depthMin !== undefined) $('section-depth-min').value = settings.depthMin;
  if (settings.depthMax !== undefined) $('section-depth-max').value = settings.depthMax;
  if (settings.valueMin !== undefined) $('section-value-min').value = settings.valueMin;
  if (settings.valueMax !== undefined) $('section-value-max').value = settings.valueMax;
  if (settings.boundaryGap !== undefined) $('section-boundary-gap').value = settings.boundaryGap;
  if (settings.minLayer !== undefined) $('section-min-layer').value = settings.minLayer;
  if (settings.showBoundaries !== undefined) $('section-show-boundaries').checked = Boolean(settings.showBoundaries);
  if (settings.barrierThickness !== undefined) $('section-barrier-thickness').checked = Boolean(settings.barrierThickness);
  state.sectionViewXRange = settings.xRange && Number.isFinite(Number(settings.xRange.min)) && Number.isFinite(Number(settings.xRange.max))
    ? { min: Number(settings.xRange.min), max: Number(settings.xRange.max) }
    : null;
  appendLog('Restored section scene settings.');
  return true;
}

async function restoreSectionBoundariesFromFile(path, result, trajectory) {
  if (!path || !state.sectionMesh || !state.sectionMesh.mesh) return;
  const wellName = sectionTrajectoryName(trajectory) || (result && result.well_name) || '';
  try {
    const loaded = await window.petrel.run('load-section-boundaries', {
      path,
      wellName: state.sectionWellNameMap[wellName] || wellName,
      columnMapping: currentColumnMapping()
    });
    const boundaries = sectionBoundariesFromSavedRecords(loaded.records || [], state.sectionMesh.mesh, result);
    if (!boundaries.length) return;
    state.sectionBoundaries = boundaries;
    redrawCurrentSectionMesh();
    const selected = $('section-well').value;
    if (selected) state.sectionSavedWells[selected] = true;
    fillSectionWells(state.sectionTrajectories);
    saveState();
    appendLog(`Restored section boundary points: ${boundaries.length} from ${path}`);
  } catch (error) {
    appendLog(`Warning: saved section boundaries were not restored: ${error.message}`);
  }
}

function sectionBoundariesFromSavedRecords(records, mesh, result) {
  const sleeves = mesh && Array.isArray(mesh.sleeves) ? mesh.sleeves : [];
  const boundaries = [];
  for (const record of records || []) {
    const sleeve = findSavedBoundarySleeve(record, sleeves);
    if (!sleeve) continue;
    const boundary = {
      well: record.well || sleeve.well || (result && result.well_name) || '',
      port: record.port != null ? record.port : sleeve.port,
      md: Number.isFinite(numericCell(record.md)) ? numericCell(record.md) : sleeve.md,
      x: sleeve.x,
      y: sleeve.depth,
      worldX: Number.isFinite(numericCell(record.X)) ? numericCell(record.X) : sleeve.worldX,
      worldY: Number.isFinite(numericCell(record.Y)) ? numericCell(record.Y) : sleeve.worldY,
      TVDSS_PORT: Number.isFinite(numericCell(record.TVDSS_PORT)) ? numericCell(record.TVDSS_PORT) : sleeve.depth,
      TVDSS_TOP_TOTAL: numericCell(record.TVDSS_TOP_TOTAL),
      TVDSS_BOT_TOTAL: numericCell(record.TVDSS_BOT_TOTAL),
      TVDSS_TOP_LOCAL: numericCell(record.TVDSS_TOP_LOCAL),
      TVDSS_BOT_LOCAL: numericCell(record.TVDSS_BOT_LOCAL),
      TVDSS_TOP_BARRIER_LOCAL: numericCell(record.TVDSS_TOP_BARRIER_LOCAL),
      TVDSS_BOT_BARRIER_LOCAL: numericCell(record.TVDSS_BOT_BARRIER_LOCAL),
      BARRIER_TOP_LOCAL: numericCell(record.BARRIER_TOP_LOCAL),
      BARRIER_BOT_LOCAL: numericCell(record.BARRIER_BOT_LOCAL)
    };
    normalizeBoundaryOrder(boundary);
    boundaries.push(boundary);
  }
  return boundaries;
}

function findSavedBoundarySleeve(record, sleeves) {
  if (!sleeves || !sleeves.length) return null;
  const portKey = normalizeLookupTextSafe(record && record.port);
  const md = numericCell(record && record.md);
  const wellKey = normalizeLookupTextSafe(record && record.well);
  const candidates = sleeves.filter(sleeve => {
    if (wellKey && normalizeLookupTextSafe(sleeve.well) && normalizeLookupTextSafe(sleeve.well) !== wellKey) return false;
    if (portKey && normalizeLookupTextSafe(sleeve.port) && normalizeLookupTextSafe(sleeve.port) !== portKey) return false;
    return true;
  });
  const pool = candidates.length ? candidates : sleeves;
  if (Number.isFinite(md)) {
    const best = pool
      .map(sleeve => ({ sleeve, distance: Math.abs(numericCell(sleeve.md) - md) }))
      .filter(item => Number.isFinite(item.distance))
      .sort((left, right) => left.distance - right.distance)[0];
    if (best && best.distance <= 0.5) return best.sleeve;
  }
  return pool.length === 1 ? pool[0] : null;
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
  const sleeveDepthInterval = sectionSleeveDepthInterval(rows, axis, result.sleeveMarkers || [], 50, result);
  const propertyDepthCoreInterval = sleeveDepthInterval || propertyDepthCoreIntervalRaw;
  const propertyDepthInterval = sleeveDepthInterval || sectionPropertyDepthInterval(validRows, 30);
  const autoXInterval = sectionXDisplayInterval(rows, axis, propertyDepthCoreInterval, finiteX);
  const displayXInterval = state.sectionViewXRange && Number.isFinite(state.sectionViewXRange.min) && Number.isFinite(state.sectionViewXRange.max)
    ? state.sectionViewXRange
    : autoXInterval;
  let depthMin = numericInput('section-depth-min');
  let depthMax = numericInput('section-depth-max');
  if (sleeveDepthInterval) {
    if (!Number.isFinite(depthMin)) depthMin = sleeveDepthInterval.min;
    if (!Number.isFinite(depthMax)) depthMax = sleeveDepthInterval.max;
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

function sectionSleeveDepthInterval(rows, axis, markers, padding, result) {
  if (!markers || !markers.length) return null;
  const trajectory = sectionTrajectoryForSleeves(result, rows, axis)
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

function sectionSleevePoints(rows, common, markers, result) {
  if (!markers || !markers.length) return [];
  const trajectory = sectionTrajectoryForSleeves(result, rows, common.axis)
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

function sectionTrajectoryForSleeves(result, rows, axis) {
  const rawPoints = result && Array.isArray(result.trajectory_points) ? result.trajectory_points : [];
  const points = rawPoints
    .map(point => {
      const md = numericCell(point.md);
      const x = numericCell(point[axis]);
      const depth = sectionTrajectoryDepth(point.z);
      const worldX = numericCell(point.x);
      const worldY = numericCell(point.y);
      if (!Number.isFinite(md) || !Number.isFinite(x) || !Number.isFinite(depth)) return null;
      return {
        station: NaN,
        x,
        depth,
        md,
        distance: numericCell(point.distance),
        horizontal_distance: numericCell(point.horizontal_distance),
        worldX,
        worldY
      };
    })
    .filter(Boolean);
  if (points.length >= 2) return points;
  return sectionStationTrajectoryPoints(rows, axis);
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
  target.innerHTML = '<canvas class="section-mesh-canvas"></canvas>';
  const canvas = target.querySelector('canvas');
  const inspector = $('section-cell-inspector');
  clearSectionCellInspector(inspector);
  const mesh = buildSectionLayerMesh(common.validRows, common.axis, common.depthMin, common.depthMax, common.valueMin, common.valueMax, common.xMin, common.xMax);
  mesh.trajectory = sectionTrajectoryPoints(result.rows || [], common);
  mesh.sleeves = sectionSleevePoints(result.rows || [], common, result.sleeveMarkers || [], result);
  mesh.horizons = sectionHorizonLines(result, common);
  state.sectionMesh = { common, result, mesh };
  drawSectionLayerMesh(canvas, mesh, common, result);
  canvas.addEventListener('mousedown', event => {
    if (startSectionAxisDrag(event, canvas, mesh)) return;
    startSectionBoundaryDrag(event, canvas, mesh);
  });
  canvas.addEventListener('wheel', event => zoomSectionMesh(event, canvas, mesh), { passive: false });
  canvas.addEventListener('mousemove', event => {
    if (state.sectionAxisDrag) {
      dragSectionAxis(event, canvas);
      return;
    }
    if (state.sectionBoundaryDrag) {
      dragSectionBoundary(event, canvas);
      return;
    }
    updateSectionMeshCursor(event, canvas, mesh);
    updateSectionCellInspector(event, canvas, inspector, mesh, result);
  });
  canvas.addEventListener('mouseleave', () => {
    if (!state.sectionBoundaryDrag && !state.sectionAxisDrag) {
      clearSectionCellInspector(inspector);
      canvas.style.cursor = '';
    }
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

  drawSectionMeshHorizons(ctx, frame, mesh);
  drawSectionMeshTrajectory(ctx, frame, mesh);
  drawSectionMeshSleeves(ctx, frame, mesh);
  drawSectionMeshBoundaries(ctx, frame, mesh);
  drawSectionMeshAxes(ctx, frame, mesh, common, result);
  drawSectionMeshColorbar(ctx, frame, mesh, result);
}

function sectionHorizonLines(result, common) {
  const selected = selectedSectionHorizonUuids();
  if (!selected.size) return [];
  return (result.horizons || [])
    .filter(horizon => selected.has(horizon.uuid))
    .map(horizon => ({
      ...horizon,
      points: (horizon.points || [])
        .map(point => ({
          x: numericCell(point[common.axis]),
          depth: numericCell(point.depth),
          station: Number(point.station_index)
        }))
        .filter(point => Number.isFinite(point.x) && Number.isFinite(point.depth))
        .sort((left, right) => left.x - right.x || left.station - right.station)
    }))
    .filter(horizon => horizon.points.length > 1);
}

function drawSectionMeshHorizons(ctx, frame, mesh) {
  const palette = ['#111827', '#d97706', '#047857', '#1d4ed8', '#be123c', '#6d28d9'];
  const horizons = mesh.horizons || [];
  if (!horizons.length) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(frame.left, frame.top, frame.width, frame.height);
  ctx.clip();
  ctx.font = '600 10px Arial, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'bottom';
  horizons.forEach((horizon, index) => {
    const color = palette[index % palette.length];
    const points = horizon.points
      .filter(point => point.x >= mesh.xMin && point.x <= mesh.xMax && point.depth >= mesh.yMin && point.depth <= mesh.yMax)
      .map(point => sectionMeshToScreen(point.x, point.depth, frame, mesh));
    if (points.length < 2) return;
    drawPolyline(ctx, points, '#ffffff', 5, 0.9);
    drawPolyline(ctx, points, color, 2.2, 1);
    const labelPoint = points[points.length - 1];
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#ffffff';
    ctx.strokeText(horizon.title, labelPoint.x - 5, labelPoint.y - 3);
    ctx.fillStyle = color;
    ctx.fillText(horizon.title, labelPoint.x - 5, labelPoint.y - 3);
  });
  ctx.restore();
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
    TVDSS_BOT_LOCAL: { color: '#7c3aed', label: 'BL' },
    TVDSS_TOP_BARRIER_LOCAL: { color: '#dc2626', label: 'TB' },
    TVDSS_BOT_BARRIER_LOCAL: { color: '#991b1b', label: 'BB' }
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
  const settings = sectionBoundarySettings();
  const boundaries = [];
  for (const sleeve of mesh.sleeves) {
    const cells = sectionBoundaryCellsAtSleeve(common.validRows || [], common.axis, sleeve, valueRange);
    const continuousBodies = sectionMergeIntervals(cells.map(cell => ({ top: cell.top, base: cell.base })), 1e-6)
      .filter(interval => sectionIntervalThickness(interval) >= settings.minLayer);
    const intervals = sectionMergeIntervals(continuousBodies, settings.gap);
    if (!intervals.length) continue;
    const local = sectionNearestInterval(intervals, sleeve.depth);
    const barriers = $('section-barrier-thickness').checked
      ? sectionLocalBarrierBounds(continuousBodies, local)
      : { topPoint: NaN, botPoint: NaN, topThickness: NaN, botThickness: NaN };
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
      TVDSS_BOT_LOCAL: local ? local.base : totalRange.max,
      TVDSS_TOP_BARRIER_LOCAL: barriers.topPoint,
      TVDSS_BOT_BARRIER_LOCAL: barriers.botPoint,
      BARRIER_TOP_LOCAL: barriers.topThickness,
      BARRIER_BOT_LOCAL: barriers.botThickness
    });
  }
  state.sectionBoundaries = boundaries;
  redrawCurrentSectionMesh();
  setReady(`Auto boundaries: ${boundaries.length} sleeves, gap ${settings.gap} m, min layer ${settings.minLayer} m`);
}

function sectionBoundarySettings() {
  const gap = numericInput('section-boundary-gap');
  const minLayer = numericInput('section-min-layer');
  return {
    gap: Number.isFinite(gap) ? Math.max(0, gap) : 2,
    minLayer: Number.isFinite(minLayer) ? Math.max(0, minLayer) : 0
  };
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

function sectionIntervalThickness(interval) {
  if (!interval) return 0;
  const top = Number(interval.top);
  const base = Number(interval.base);
  if (!Number.isFinite(top) || !Number.isFinite(base)) return 0;
  return Math.abs(base - top);
}

function sectionLocalBarrierBounds(bodies, local) {
  if (!local) return { topPoint: NaN, botPoint: NaN, topThickness: NaN, botThickness: NaN };
  const sorted = (bodies || []).slice().sort((left, right) => left.top - right.top);
  const previous = sorted
    .filter(item => item.base <= local.top + 1e-6)
    .sort((left, right) => right.base - left.base)[0] || null;
  const next = sorted
    .filter(item => item.top >= local.base - 1e-6)
    .sort((left, right) => left.top - right.top)[0] || null;
  const topPoint = previous ? previous.base : local.top;
  const botPoint = next ? next.top : local.base;
  return {
    topPoint,
    botPoint,
    topThickness: Number.isFinite(topPoint) ? Math.max(0, local.top - topPoint) : NaN,
    botThickness: Number.isFinite(botPoint) ? Math.max(0, botPoint - local.base) : NaN
  };
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

function stopSectionDrag() {
  state.sectionBoundaryDrag = null;
  state.sectionAxisDrag = null;
  const canvas = document.querySelector('#section-plot canvas');
  if (canvas) canvas.style.cursor = '';
}

function normalizeBoundaryOrder(boundary) {
  if (Number.isFinite(boundary.TVDSS_TOP_TOTAL) && Number.isFinite(boundary.TVDSS_BOT_TOTAL) && boundary.TVDSS_TOP_TOTAL > boundary.TVDSS_BOT_TOTAL) {
    [boundary.TVDSS_TOP_TOTAL, boundary.TVDSS_BOT_TOTAL] = [boundary.TVDSS_BOT_TOTAL, boundary.TVDSS_TOP_TOTAL];
  }
  if (Number.isFinite(boundary.TVDSS_TOP_LOCAL) && Number.isFinite(boundary.TVDSS_BOT_LOCAL) && boundary.TVDSS_TOP_LOCAL > boundary.TVDSS_BOT_LOCAL) {
    [boundary.TVDSS_TOP_LOCAL, boundary.TVDSS_BOT_LOCAL] = [boundary.TVDSS_BOT_LOCAL, boundary.TVDSS_TOP_LOCAL];
  }
  if (Number.isFinite(boundary.TVDSS_TOP_BARRIER_LOCAL) && Number.isFinite(boundary.TVDSS_TOP_LOCAL)) {
    boundary.TVDSS_TOP_BARRIER_LOCAL = Math.min(boundary.TVDSS_TOP_BARRIER_LOCAL, boundary.TVDSS_TOP_LOCAL);
  }
  if (Number.isFinite(boundary.TVDSS_BOT_BARRIER_LOCAL) && Number.isFinite(boundary.TVDSS_BOT_LOCAL)) {
    boundary.TVDSS_BOT_BARRIER_LOCAL = Math.max(boundary.TVDSS_BOT_BARRIER_LOCAL, boundary.TVDSS_BOT_LOCAL);
  }
  updateBoundaryBarrierThickness(boundary);
}

function updateBoundaryBarrierThickness(boundary) {
  boundary.BARRIER_TOP_LOCAL = Number.isFinite(boundary.TVDSS_TOP_LOCAL) && Number.isFinite(boundary.TVDSS_TOP_BARRIER_LOCAL)
    ? Math.max(0, boundary.TVDSS_TOP_LOCAL - boundary.TVDSS_TOP_BARRIER_LOCAL)
    : NaN;
  boundary.BARRIER_BOT_LOCAL = Number.isFinite(boundary.TVDSS_BOT_LOCAL) && Number.isFinite(boundary.TVDSS_BOT_BARRIER_LOCAL)
    ? Math.max(0, boundary.TVDSS_BOT_BARRIER_LOCAL - boundary.TVDSS_BOT_LOCAL)
    : NaN;
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
  updateSectionBoundaryFileDefault();
  const outputPath = sectionBoundaryOutputPathFromInput();
  if (!outputPath) return fail(new Error('Enter boundary file name.'));
  setBusy('Saving boundaries', basename(outputPath));
  try {
    state.currentSectionSceneKey = currentSectionSceneKeyForPath(outputPath);
    saveCurrentSectionSceneSettings();
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
      TVDSS_BOT_LOCAL: boundary.TVDSS_BOT_LOCAL,
      TVDSS_TOP_BARRIER_LOCAL: boundary.TVDSS_TOP_BARRIER_LOCAL,
      TVDSS_BOT_BARRIER_LOCAL: boundary.TVDSS_BOT_BARRIER_LOCAL,
      BARRIER_TOP_LOCAL: boundary.BARRIER_TOP_LOCAL,
      BARRIER_BOT_LOCAL: boundary.BARRIER_BOT_LOCAL
    }));
    const result = await window.petrel.run('save-section-boundaries', {
      path,
      outputPath,
      columnMapping: currentColumnMapping(),
      records
    });
    const savedPath = result.outputPath || outputPath;
    if (result.rowsUpdated > 0 && savedPath) {
      $('sleeves-path').value = savedPath;
      $('sleeves-name').value = basename(savedPath);
      $('metrics-intervals').value = savedPath;
      state.columnMapping = currentColumnMapping();
      state.sectionBoundaryPath = savedPath;
    }
    if (savedPath) state.sectionBoundaryPath = savedPath;
    updateWorkflowSummaries();
    const selected = $('section-well').value;
    if (selected) state.sectionSavedWells[selected] = true;
    await saveCurrentSectionCache();
    if (selected && state.currentSectionPayload && state.sectionResult) state.sectionCachedWells[selected] = true;
    fillSectionWells(state.sectionTrajectories);
    saveState();
    const skipped = Number(result.rowsSkipped || 0);
    setReady(`Saved boundaries: ${result.rowsUpdated || 0} rows${skipped ? `, skipped ${skipped}` : ''}`);
    appendLog(`Section boundaries saved: ${savedPath}`);
    if (skipped) appendLog(`Warning: ${skipped} sleeve row(s) were not matched and were not updated.`);
  } catch (error) {
    fail(error);
  }
}

async function saveCurrentSectionCache() {
  if (!state.currentSectionPayload || !state.sectionResult) return;
  try {
    await window.petrel.run('save-section-cache', {
      sectionPayload: state.currentSectionPayload,
      result: sectionCacheResultPayload(state.sectionResult)
    });
    appendLog('Section cache saved.');
  } catch (error) {
    appendLog(`Warning: section cache was not saved: ${error.message}`);
  }
}

function sectionCacheResultPayload(result) {
  const payload = Object.assign({}, result || {});
  delete payload.event;
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (rows.length) {
    const keys = Object.keys(rows[0]);
    payload.rowColumns = Object.fromEntries(keys.map(key => [key, rows.map(row => row[key])]));
    delete payload.rows;
  }
  return payload;
}

function unpackSectionResult(result) {
  if (!result || Array.isArray(result.rows) || !result.rowColumns) return result;
  const columns = result.rowColumns;
  const keys = Object.keys(columns);
  const rowCount = keys.length && Array.isArray(columns[keys[0]]) ? columns[keys[0]].length : 0;
  const rows = new Array(rowCount);
  for (let index = 0; index < rowCount; index += 1) {
    const row = {};
    for (const key of keys) row[key] = columns[key][index];
    rows[index] = row;
  }
  result.rows = rows;
  delete result.rowColumns;
  return result;
}

async function clearSectionCache() {
  setBusy('Clearing section cache', 'Removing saved section rasters');
  try {
    const result = await window.petrel.run('clear-section-cache', {});
    state.sectionCachedWells = {};
    fillSectionWells(state.sectionTrajectories);
    saveState();
    setReady('Section cache cleared');
    appendLog(`Section cache cleared: ${result.cachePath || ''}`);
  } catch (error) {
    fail(error);
  }
}

function sectionBoundaryOutputPath(path) {
  const dir = dirname(path);
  const name = stripExtension(basename(path));
  const normalized = name.toLowerCase();
  const filename = name
    ? `${normalized.endsWith('_boundaries') ? name : `${name}_boundaries`}.xlsx`
    : 'frac_list_boundaries.xlsx';
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

function sectionMeshPointFromScreen(x, y, frame, mesh) {
  const xFraction = (x - frame.left) / (frame.width || 1);
  const yFraction = (y - frame.top) / (frame.height || 1);
  return {
    x: mesh.xMin + xFraction * (mesh.xMax - mesh.xMin),
    y: mesh.yMin + yFraction * (mesh.yMax - mesh.yMin),
    xFraction,
    yFraction
  };
}

function sectionMeshInteractionRegion(x, y, frame) {
  if (!frame) return null;
  const insideX = x >= frame.left && x <= frame.right;
  const insideY = y >= frame.top && y <= frame.bottom;
  if (insideX && insideY) return { type: 'plot' };
  if (insideX && y > frame.bottom && y <= frame.bottom + 58) {
    const fraction = (x - frame.left) / (frame.width || 1);
    return {
      type: 'x-axis',
      mode: fraction < 0.18 ? 'resize-min' : (fraction > 0.82 ? 'resize-max' : 'pan')
    };
  }
  if (insideY && x >= frame.left - 76 && x < frame.left) {
    const fraction = (y - frame.top) / (frame.height || 1);
    return {
      type: 'y-axis',
      mode: fraction < 0.18 ? 'resize-min' : (fraction > 0.82 ? 'resize-max' : 'pan')
    };
  }
  return null;
}

function startSectionAxisDrag(event, canvas, mesh) {
  if (!state.sectionResult || !mesh || !mesh.frame) return false;
  const rect = canvas.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;
  const region = sectionMeshInteractionRegion(screenX, screenY, mesh.frame);
  if (!region || region.type === 'plot') return false;
  state.sectionAxisDrag = {
    type: region.type,
    mode: region.mode,
    startX: screenX,
    startY: screenY,
    xMin: mesh.xMin,
    xMax: mesh.xMax,
    yMin: mesh.yMin,
    yMax: mesh.yMax
  };
  canvas.style.cursor = sectionAxisCursor(region);
  event.preventDefault();
  return true;
}

function dragSectionAxis(event, canvas) {
  const current = state.sectionMesh;
  const drag = state.sectionAxisDrag;
  if (!current || !drag || !current.mesh || !current.mesh.frame) return;
  const rect = canvas.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;
  const frame = current.mesh.frame;
  if (drag.type === 'x-axis') {
    const range = sectionDraggedAxisRange(
      drag.xMin,
      drag.xMax,
      screenX - drag.startX,
      frame.width,
      drag.mode,
      5
    );
    state.sectionViewXRange = range;
  } else if (drag.type === 'y-axis') {
    const range = sectionDraggedAxisRange(
      drag.yMin,
      drag.yMax,
      screenY - drag.startY,
      frame.height,
      drag.mode,
      1
    );
    $('section-depth-min').value = formatInputNumber(range.min, 1);
    $('section-depth-max').value = formatInputNumber(range.max, 1);
  }
  event.preventDefault();
  paintSection(state.sectionResult);
}

function sectionDraggedAxisRange(minValue, maxValue, pixelDelta, pixelSpan, mode, minSpan) {
  const span = maxValue - minValue;
  if (!Number.isFinite(span) || span <= 0 || !Number.isFinite(pixelDelta)) return { min: minValue, max: maxValue };
  const valueDelta = (pixelDelta / Math.max(1, pixelSpan)) * span;
  if (mode === 'resize-min') {
    return sectionNormalizedRange(minValue + valueDelta, maxValue, minSpan);
  }
  if (mode === 'resize-max') {
    return sectionNormalizedRange(minValue, maxValue + valueDelta, minSpan);
  }
  return {
    min: minValue - valueDelta,
    max: maxValue - valueDelta
  };
}

function sectionNormalizedRange(minValue, maxValue, minSpan) {
  let min = minValue;
  let max = maxValue;
  if (min > max) [min, max] = [max, min];
  if (max - min < minSpan) {
    const center = (min + max) / 2;
    min = center - minSpan / 2;
    max = center + minSpan / 2;
  }
  return { min, max };
}

function updateSectionMeshCursor(event, canvas, mesh) {
  if (!mesh || !mesh.frame) {
    canvas.style.cursor = '';
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const region = sectionMeshInteractionRegion(event.clientX - rect.left, event.clientY - rect.top, mesh.frame);
  canvas.style.cursor = sectionAxisCursor(region);
}

function sectionAxisCursor(region) {
  if (!region) return '';
  if (region.type === 'x-axis') return region.mode === 'pan' ? 'grab' : 'ew-resize';
  if (region.type === 'y-axis') return region.mode === 'pan' ? 'grab' : 'ns-resize';
  return 'crosshair';
}

function zoomSectionMesh(event, canvas, mesh) {
  if (!state.sectionResult || !mesh || !mesh.frame) return;
  const rect = canvas.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;
  const frame = mesh.frame;
  const region = sectionMeshInteractionRegion(screenX, screenY, frame);
  if (!region) return;
  event.preventDefault();
  const point = sectionMeshPointFromScreen(screenX, screenY, frame, mesh);
  const factor = event.deltaY < 0 ? 0.82 : 1.22;
  if (region.type === 'plot' || region.type === 'x-axis') {
    state.sectionViewXRange = sectionZoomRange(mesh.xMin, mesh.xMax, point.x, point.xFraction, factor, 5);
  }
  if (region.type === 'plot' || region.type === 'y-axis') {
    const yRange = sectionZoomRange(mesh.yMin, mesh.yMax, point.y, point.yFraction, factor, 1);
    $('section-depth-min').value = formatInputNumber(yRange.min, 1);
    $('section-depth-max').value = formatInputNumber(yRange.max, 1);
  }
  paintSection(state.sectionResult);
}

function sectionZoomRange(minValue, maxValue, centerValue, fraction, factor, minSpan) {
  const currentSpan = maxValue - minValue;
  if (!Number.isFinite(currentSpan) || currentSpan <= 0) return { min: minValue, max: maxValue };
  const span = Math.max(minSpan, currentSpan * factor);
  const clampedFraction = Math.max(0.02, Math.min(0.98, fraction));
  return {
    min: centerValue - span * clampedFraction,
    max: centerValue + span * (1 - clampedFraction)
  };
}

function updateSectionCellInspector(event, canvas, inspector, mesh, result) {
  if (!inspector) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = findSectionMeshQuad(mesh, x, y);
  if (!hit) {
    clearSectionCellInspector(inspector);
    return;
  }
  const leftDistance = Math.abs(x - (hit.points[0].x + hit.points[3].x) / 2);
  const rightDistance = Math.abs(x - (hit.points[1].x + hit.points[2].x) / 2);
  const row = (leftDistance <= rightDistance ? hit.quad.leftCell : hit.quad.rightCell).row;
  const inspectorKey = `${row.station_index}:${row.i}:${row.j}:${row.k}`;
  if (inspector.dataset.cellKey === inspectorKey) return;
  inspector.dataset.cellKey = inspectorKey;
  const depth = numericCell(row.tvd_center);
  const fields = [
    [result.property_title || 'Value', row.value],
    ['I / J / K', `${row.i} / ${row.j} / ${row.k}`],
    ['MD, m', row.md],
    ['3D distance, m', row.distance],
    ['Horizontal distance, m', row.horizontal_distance],
    ['TVD, m', Number.isFinite(depth) ? depth : (numericCell(row.tvd_top) + numericCell(row.tvd_base)) / 2]
  ];
  inspector.innerHTML = fields.map(([label, value]) => `
    <span class="section-cell-inspector-item">
      <span class="section-cell-inspector-label">${escapeHtml(String(label))}</span>
      <span class="section-cell-inspector-value">${escapeHtml(formatSectionInspectorValue(value))}</span>
    </span>
  `).join('');
}

function clearSectionCellInspector(inspector) {
  if (!inspector) return;
  delete inspector.dataset.cellKey;
  inspector.innerHTML = '<span class="section-cell-inspector-empty">Hover over a section cell</span>';
}

function formatSectionInspectorValue(value) {
  if (typeof value === 'string' && value.trim()) return value;
  const numeric = numericCell(value);
  return Number.isFinite(numeric) ? formatAxisTick(numeric) : '-';
}

function findSectionMeshQuad(mesh, x, y) {
  for (let index = mesh.screenQuads.length - 1; index >= 0; index -= 1) {
    const candidate = mesh.screenQuads[index];
    if (x < candidate.bbox.minX || x > candidate.bbox.maxX || y < candidate.bbox.minY || y > candidate.bbox.maxY) continue;
    if (pointInPolygon(x, y, candidate.points)) return candidate;
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
    .map(model => ({
      label: model.label,
      path: model.path.trim(),
      depthOffset: Number(model.depthOffset || 0),
      gridUuid: model.gridUuid || ''
    }));
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

async function pickTable(dialogKey = 'tables') {
  return window.petrel.openFile({
    dialogKey,
    filters: [{ name: 'Tables', extensions: ['xlsx', 'xlsm', 'xls', 'csv'] }, { name: 'All files', extensions: ['*'] }]
  });
}

async function saveXlsx(name, dialogKey = 'xlsx-output') {
  return window.petrel.saveFile({
    dialogKey,
    defaultPath: name,
    filters: [{ name: 'Excel / CSV', extensions: ['xlsx', 'csv'] }]
  });
}

async function browseExtractionOutput() {
  const filename = $('output-path').value.trim() || 'extracted.xlsx';
  const sleevesDir = dirname($('sleeves-path').value.trim());
  const defaultPath = sleevesDir ? joinPath(sleevesDir, filename) : filename;
  const selected = await saveXlsx(defaultPath, 'extraction-output');
  if (!selected) return;
  $('output-path').value = basename(selected);
  saveState();
}

async function browseMetricsIntervals() {
  const selected = await pickTable('metrics-intervals');
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
  const selected = await saveXlsx(defaultPath, 'metrics-output');
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

function setAttention(message) {
  $('status-title').textContent = 'Attention';
  $('status-subtitle').textContent = message;
  appendLog(`Attention: ${message}`);
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

function currentCurveSettings() {
  const channels = [];
  const mins = [];
  const maxs = [];
  const shifts = [];
  for (let index = 1; index <= 4; index += 1) {
    channels.push($(`curve-channel-${index}`) ? $(`curve-channel-${index}`).value : '');
    mins.push($(`curve-min-${index}`) ? $(`curve-min-${index}`).value : '');
    maxs.push($(`curve-max-${index}`) ? $(`curve-max-${index}`).value : '');
    shifts.push($(`curve-shift-${index}`) ? $(`curve-shift-${index}`).value : '');
  }
  return {
    well: $('curve-well') ? $('curve-well').value : '',
    port: $('curve-port') ? $('curve-port').value : '',
    depthMode: $('curve-depth-mode') ? $('curve-depth-mode').value : 'common',
    depthMin: $('curve-depth-min') ? $('curve-depth-min').value : '',
    depthMax: $('curve-depth-max') ? $('curve-depth-max').value : '',
    channels,
    mins,
    maxs,
    shifts
  };
}

function saveState() {
  state.extractionSelectedProperties = currentExtractionSelectedProperties();
  state.columnMapping = currentColumnMapping();
  state.curveSettings = currentCurveSettings();
  const data = {
    models: state.models,
    sleevesPath: $('sleeves-path').value,
    selectedWells: state.selectedWells,
    extractionSelectedProperties: state.extractionSelectedProperties,
    columnMapping: state.columnMapping,
    hasSavedWellSelection: state.hasSavedWellSelection,
    overwriteSleeveXY: $('overwrite-sleeve-xy').checked,
    outputPath: $('output-path').value,
    skipInactive: $('skip-inactive').checked,
    writeDiagnostics: $('write-diagnostics').checked,
    parallelWorkers: $('parallel-workers').value,
    metricsExtracted: $('metrics-extracted').value,
    metricsIntervals: $('metrics-intervals').value,
    metricsOutput: $('metrics-output').value,
    curvePath: $('curve-path').value,
    curveSettings: state.curveSettings,
    sectionWellNameMap: state.sectionWellNameMap,
    wellAssignments: state.wellAssignments,
    sectionSavedWells: state.sectionSavedWells,
    sectionCachedWells: state.sectionCachedWells,
    sectionCacheLabelVersion: 2,
    sectionBoundaryPath: state.sectionBoundaryPath,
    sectionBoundaryFileName: $('section-boundary-file').value,
    sectionSceneSettings: state.sectionSceneSettings,
    sectionStep: $('section-step').value,
    sectionAxis: $('section-axis').value,
    sectionSkipInactive: $('section-skip-inactive').checked,
    sectionBoundaryGap: $('section-boundary-gap').value,
    sectionMinLayer: $('section-min-layer').value,
    sectionShowBoundaries: $('section-show-boundaries').checked,
    sectionBarrierThickness: $('section-barrier-thickness').checked,
    sectionSelectedHorizons: state.sectionSelectedHorizons
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
    if (data.wellAssignments && typeof data.wellAssignments === 'object') state.wellAssignments = data.wellAssignments;
    if (data.sectionSavedWells && typeof data.sectionSavedWells === 'object') state.sectionSavedWells = data.sectionSavedWells;
    if (data.sectionCacheLabelVersion === 2 && data.sectionCachedWells && typeof data.sectionCachedWells === 'object') {
      state.sectionCachedWells = data.sectionCachedWells;
    }
    if (data.sectionBoundaryPath) state.sectionBoundaryPath = data.sectionBoundaryPath;
    if (data.sectionBoundaryFileName) {
      state.sectionBoundaryFileName = data.sectionBoundaryFileName;
      $('section-boundary-file').value = data.sectionBoundaryFileName;
    } else if (data.sectionBoundaryPath) {
      state.sectionBoundaryFileName = basename(data.sectionBoundaryPath);
      $('section-boundary-file').value = state.sectionBoundaryFileName;
    }
    if (data.sectionSceneSettings && typeof data.sectionSceneSettings === 'object') state.sectionSceneSettings = data.sectionSceneSettings;
    if (data.sectionSelectedHorizons && typeof data.sectionSelectedHorizons === 'object') state.sectionSelectedHorizons = data.sectionSelectedHorizons;
    if (data.curveSettings && typeof data.curveSettings === 'object') state.curveSettings = data.curveSettings;
    state.hasSavedWellSelection = Boolean(data.hasSavedWellSelection);
    renderModels();
    $('sleeves-path').value = data.sleevesPath || '';
    $('sleeves-name').value = basename(data.sleevesPath || '');
    $('output-path').value = basename(data.outputPath || '');
    if (data.overwriteSleeveXY !== undefined) $('overwrite-sleeve-xy').checked = Boolean(data.overwriteSleeveXY);
    if (data.skipInactive !== undefined) $('skip-inactive').checked = Boolean(data.skipInactive);
    if (data.writeDiagnostics !== undefined) $('write-diagnostics').checked = Boolean(data.writeDiagnostics);
    if (data.parallelWorkers) $('parallel-workers').value = data.parallelWorkers;
    $('metrics-extracted').value = data.metricsExtracted || '';
    $('metrics-intervals').value = data.metricsIntervals || '';
    $('metrics-output').value = basename(data.metricsOutput || '');
    $('curve-path').value = data.curvePath || '';
    applySavedCurveRanges();
    if (data.sectionStep) $('section-step').value = data.sectionStep;
    if (data.sectionAxis) $('section-axis').value = data.sectionAxis;
    if (data.sectionSkipInactive !== undefined) $('section-skip-inactive').checked = Boolean(data.sectionSkipInactive);
    if (data.sectionBoundaryGap !== undefined) $('section-boundary-gap').value = data.sectionBoundaryGap;
    if (data.sectionMinLayer !== undefined) $('section-min-layer').value = data.sectionMinLayer;
    if (data.sectionShowBoundaries !== undefined) $('section-show-boundaries').checked = Boolean(data.sectionShowBoundaries);
    if (data.sectionBarrierThickness !== undefined) $('section-barrier-thickness').checked = Boolean(data.sectionBarrierThickness);
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
