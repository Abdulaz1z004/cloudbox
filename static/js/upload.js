// Real XHR upload with true progress tracking
document.getElementById('upload-form').addEventListener('submit', function(e) {
  e.preventDefault();

  var fileInput = document.getElementById('file-input');
  var file = fileInput.files[0];
  if (!file) {
    alert('Please select a file first.');
    return;
  }

  var progressSection = document.getElementById('progress-section');
  var progressBar     = document.getElementById('progress-bar');
  var progressText    = document.getElementById('progress-text');
  var submitBtn       = document.getElementById('submit-btn');

  progressSection.style.display = 'block';
  submitBtn.disabled = true;
  submitBtn.textContent = 'Uploading…';

  var formData = new FormData();
  formData.append('file', file);

  var xhr = new XMLHttpRequest();

  xhr.upload.onprogress = function(event) {
    if (event.lengthComputable) {
      var pct = Math.round((event.loaded / event.total) * 100);
      progressBar.style.width = pct + '%';
      progressText.textContent = pct + '%';
    }
  };

  xhr.onload = function() {
    if (xhr.status === 200) {
      progressBar.style.width = '100%';
      progressText.textContent = '100%';
      progressBar.style.background = '#0D9488';
      setTimeout(function() {
        window.location.href = '/dashboard';
      }, 800);
    } else {
      progressBar.style.background = '#ef4444';
      progressText.textContent = 'Upload failed. Try again.';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Upload File';
    }
  };

  xhr.onerror = function() {
    progressBar.style.background = '#ef4444';
    progressText.textContent = 'Network error. Check your connection.';
    submitBtn.disabled = false;
    submitBtn.textContent = 'Upload File';
  };

  xhr.open('POST', '/upload', true);
  xhr.send(formData);
});

// Drag-and-drop styling
var dropZone = document.getElementById('drop-zone');
if (dropZone) {
  dropZone.addEventListener('dragover', function(e) {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });
  dropZone.addEventListener('dragleave', function() {
    dropZone.classList.remove('dragover');
  });
  dropZone.addEventListener('drop', function(e) {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    var files = e.dataTransfer.files;
    if (files.length > 0) {
      document.getElementById('file-input').files = files;
      var label = document.getElementById('file-label');
      if (label) label.textContent = files[0].name;
    }
  });
}
