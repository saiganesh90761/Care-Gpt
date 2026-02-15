(function () {
  const API = window.API = {
    base: '',
    triage: function (payload) {
      return fetch(API.base + '/api/triage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || 'Triage failed'); });
        return r.json();
      });
    },
    uploadDocument: function (file) {
      var fd = new FormData();
      fd.append('document', file);
      return fetch(API.base + '/api/upload-document', {
        method: 'POST',
        body: fd,
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || 'Upload failed'); });
        return r.json();
      });
    },
    analyzeDocumentImage: function (file) {
      var fd = new FormData();
      fd.append('image', file);
      return fetch(API.base + '/api/analyze-document-image', {
        method: 'POST',
        body: fd,
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || 'Analysis failed'); });
        return r.json();
      });
    },
    dashboardSummary: function () {
      return fetch(API.base + '/api/dashboard/summary').then(function (r) { return r.json(); });
    },
    dashboardHistory: function () {
      return fetch(API.base + '/api/dashboard/history').then(function (r) { return r.json(); });
    },
  };

  function riskBadgeClass(level) {
    if (level === 'High') return 'badge-high';
    if (level === 'Medium') return 'badge-medium';
    return 'badge-low';
  }

  function riskValueClass(level) {
    if (level === 'High') return 'risk-high';
    if (level === 'Medium') return 'risk-medium';
    return 'risk-low';
  }

  function impactClass(impact) {
    if (impact === 'high') return 'high';
    if (impact === 'medium') return 'medium';
    return 'low';
  }

  window.loadDashboardSummary = function () {
    API.dashboardSummary().then(function (data) {
      var byRisk = data.by_risk_level || {};
      var elLow = document.getElementById('stat-low');
      var elMed = document.getElementById('stat-medium');
      var elHigh = document.getElementById('stat-high');
      if (elLow) elLow.textContent = byRisk.Low || 0;
      if (elMed) elMed.textContent = byRisk.Medium || 0;
      if (elHigh) elHigh.textContent = byRisk.High || 0;

      var deptContainer = document.getElementById('dept-bars');
      if (deptContainer) {
        var byDept = data.by_department || {};
        var total = data.total_triages || 1;
        deptContainer.innerHTML = Object.keys(byDept).length
          ? Object.keys(byDept).map(function (dept) {
              var count = byDept[dept];
              var pct = total ? Math.round((count / total) * 100) : 0;
              return '<div class="dept-item"><div class="dept-item-name">' + escapeHtml(dept) + '</div><div class="dept-item-bar"><div class="dept-item-fill" style="width:' + pct + '%"></div></div><div class="dept-item-count">' + count + '</div></div>';
            }).join('')
          : '<p class="empty-state" style="margin:0;">No data yet.</p>';
      }

      var recentList = document.getElementById('recent-triage-list');
      if (recentList && data.recent && data.recent.length) {
        recentList.innerHTML = data.recent.map(function (r) {
          var badgeClass = riskBadgeClass(r.risk_level);
          var riskBadge = '<span class="badge ' + badgeClass + '">' + escapeHtml(r.risk_level) + '</span>';
          var sym = (r.patient_input && r.patient_input.symptoms) ? r.patient_input.symptoms.substring(0, 60) + (r.patient_input.symptoms.length > 60 ? '…' : '') : '—';
          return '<div class="recent-item"><div><p class="recent-item-dept">' + escapeHtml(r.recommended_department) + '</p><p class="recent-item-symptoms">' + escapeHtml(sym) + '</p></div><div class="recent-item-meta">' + riskBadge + '<span style="font-size:0.75rem;color:var(--color-text-muted)">' + (r.confidence_score ? Math.round(r.confidence_score * 100) + '%' : '') + '</span></div></div>';
        }).join('');
      }
    }).catch(function () {
      var recentList = document.getElementById('recent-triage-list');
      if (recentList) recentList.innerHTML = '<p class="empty-state text-slate-500">Could not load summary.</p>';
    });
  };

  function escapeHtml(s) {
    if (s == null) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function renderTriageResult(data) {
    var risk = data.risk_level || 'Low';
    var conf = data.confidence_score != null ? Math.round(data.confidence_score * 100) : 0;
    var dept = data.recommended_department || 'General Medicine';
    var alt = data.alternative_departments || [];
    var summary = data.summary || '';
    var riskValClass = riskValueClass(risk);

    var html = '';
    html += '<div class="result-row"><span class="result-label">Risk level</span><span class="result-value ' + riskValClass + '">' + escapeHtml(risk) + '</span></div>';
    html += '<div class="result-row"><span class="result-label">Confidence</span><span class="result-value">' + conf + '%</span></div>';
    html += '<div class="result-row"><span class="result-label">Recommended department</span></div>';
    html += '<p class="result-dept" style="margin:0 0 0.75rem 0">' + escapeHtml(dept) + '</p>';
    if (alt.length) {
      html += '<p style="font-size:0.8125rem;color:var(--color-text-muted);margin:0 0 0.75rem 0">Alternatives: ' + alt.map(escapeHtml).join(', ') + '</p>';
    }
    if (summary) html += '<p class="result-summary">' + escapeHtml(summary) + '</p>';
    return html;
  }

  function renderExplainability(factors) {
    if (!factors || !factors.length) return '<p style="font-size:0.875rem;color:var(--color-text-muted)">No factors returned.</p>';
    var html = '<ul class="explain-list">';
    factors.forEach(function (f) {
      html += '<li class="explain-item"><span class="explain-factor">' + escapeHtml(f.factor) + '</span><span class="explain-impact ' + impactClass(f.impact) + '">(' + f.impact + ')</span><p class="explain-desc">' + escapeHtml(f.description) + '</p></li>';
    });
    html += '</ul>';
    return html;
  }

  window.initSymptomsPage = function () {
    var form = document.getElementById('triage-form');
    var resultPanel = document.getElementById('result-panel');
    var resultContent = document.getElementById('result-content');
    var explainPanel = document.getElementById('explain-panel');
    var explainContent = document.getElementById('explain-content');
    var btnSubmit = document.getElementById('btn-submit');
    var uploadInput = document.getElementById('doc-upload');
    var btnUpload = document.getElementById('btn-upload');
    var uploadStatus = document.getElementById('upload-status');

    function fillFormFromPatient(p) {
      if (!p) return;
      if (p.age != null) document.getElementById('age').value = p.age;
      if (p.gender) document.getElementById('gender').value = p.gender;
      if (p.symptoms) document.getElementById('symptoms').value = p.symptoms;
      if (p.blood_pressure_systolic != null && p.blood_pressure_diastolic != null) {
        document.getElementById('blood_pressure').value = p.blood_pressure_systolic + '/' + p.blood_pressure_diastolic;
      } else if (p.blood_pressure_systolic != null) {
        document.getElementById('blood_pressure').value = p.blood_pressure_systolic;
      }
      if (p.heart_rate != null) document.getElementById('heart_rate').value = p.heart_rate;
      if (p.temperature != null) document.getElementById('temperature').value = p.temperature;
      if (p.pre_existing_conditions && p.pre_existing_conditions.length) {
        document.getElementById('pre_existing_conditions').value = p.pre_existing_conditions.join(', ');
      }
    }

    if (btnUpload && uploadInput) {
      btnUpload.addEventListener('click', function () { uploadInput.click(); });
      uploadInput.addEventListener('change', function () {
        var file = uploadInput.files && uploadInput.files[0];
        if (!file) return;
        uploadStatus.textContent = 'Uploading…';
        API.uploadDocument(file).then(function (res) {
          uploadStatus.textContent = 'Loaded.';
          fillFormFromPatient(res.patient);
        }).catch(function (err) {
          uploadStatus.textContent = err.message || 'Upload failed';
        });
      });
    }

    var ehrImageInput = document.getElementById('ehr-image-upload');
    var btnEhrImage = document.getElementById('btn-ehr-image');
    var extractionOutput = document.getElementById('image-extraction-output');
    var extractionText = document.getElementById('image-extraction-text');
    var extractionError = document.getElementById('image-extraction-error');
    if (btnEhrImage && ehrImageInput) {
      btnEhrImage.addEventListener('click', function () { ehrImageInput.click(); });
      ehrImageInput.addEventListener('change', function () {
        var file = ehrImageInput.files && ehrImageInput.files[0];
        if (!file) return;
        if (extractionOutput) {
          extractionOutput.classList.remove('hidden');
          if (extractionError) { extractionError.classList.add('hidden'); extractionError.textContent = ''; }
        }
        uploadStatus.textContent = 'Analyzing image with AI…';
        API.analyzeDocumentImage(file).then(function (res) {
          uploadStatus.textContent = 'Done. Form filled from extraction.';
          fillFormFromPatient(res.patient);
          var raw = (res.patient && res.patient.raw_extraction) ? res.patient.raw_extraction : (res.patient && res.patient.raw) ? res.patient.raw : 'No text extracted.';
          if (extractionText) extractionText.textContent = raw;
          if (extractionError) { extractionError.classList.add('hidden'); extractionError.textContent = ''; }
        }).catch(function (err) {
          uploadStatus.textContent = 'Analysis failed.';
          if (extractionText) extractionText.textContent = '';
          if (extractionError) {
            extractionError.textContent = err.message || 'Analysis failed. Check your image and try again.';
            extractionError.classList.remove('hidden');
          }
        });
      });
    }

    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var age = form.age.value;
        var gender = form.gender.value;
        var symptoms = form.symptoms.value.trim();
        var blood_pressure = form.blood_pressure.value.trim();
        var heart_rate = form.heart_rate.value;
        var temperature = form.temperature.value;
        var conditions = form.pre_existing_conditions.value;
        var pre_existing_conditions = conditions ? conditions.split(/[,;]/).map(function (s) { return s.trim(); }).filter(Boolean) : [];

        if (!symptoms) {
          alert('Please enter symptoms.');
          return;
        }

        btnSubmit.disabled = true;
        btnSubmit.textContent = 'Analyzing…';
        API.triage({
          age: age ? parseInt(age, 10) : 35,
          gender: gender || 'Unknown',
          symptoms: symptoms,
          blood_pressure: blood_pressure || undefined,
          heart_rate: heart_rate ? parseInt(heart_rate, 10) : undefined,
          temperature: temperature ? parseFloat(temperature) : undefined,
          pre_existing_conditions: pre_existing_conditions,
        }).then(function (data) {
          resultContent.innerHTML = renderTriageResult(data);
          explainContent.innerHTML = renderExplainability(data.contributing_factors);
          resultPanel.classList.remove('hidden');
          explainPanel.classList.remove('hidden');
          if (typeof loadDashboardSummary === 'function') loadDashboardSummary();
        }).catch(function (err) {
          alert(err.message || 'Triage request failed.');
        }).finally(function () {
          btnSubmit.disabled = false;
          btnSubmit.innerHTML = '<span class="material-symbols-outlined" style="font-size:1.25rem">medical_services</span> Run AI triage';
        });
      });
    }
  };
})();
