function openModal(id) {
  document.getElementById(id).style.display = 'flex';
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

function openEditModal(contactId) {
  fetch('/contacts/get/' + contactId)
    .then(function(res) { return res.json(); })
    .then(function(data) {
      document.getElementById('edit-full-name').value = data.full_name;
      document.getElementById('edit-email').value     = data.email;
      document.getElementById('edit-company').value   = data.company   || '';
      setSelectValue('edit-storage', data.storage_limit);
      setSelectValue('edit-status',  data.status);
      setSelectValue('edit-plan',    data.plan);
      document.getElementById('edit-form').action = '/contacts/edit/' + contactId;
      openModal('edit-modal');
    })
    .catch(function() {
      alert('Could not load client data. Please try again.');
    });
}

function setSelectValue(selectId, value) {
  var sel = document.getElementById(selectId);
  for (var i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === value || sel.options[i].text === value) {
      sel.selectedIndex = i;
      return;
    }
  }
}

// Close modal when clicking outside
document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) {
      overlay.style.display = 'none';
    }
  });
});
