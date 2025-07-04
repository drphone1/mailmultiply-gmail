// Base URL for API calls - adjust if your backend runs elsewhere
const API_BASE_URL = 'http://localhost:8000';

document.addEventListener('DOMContentLoaded', () => {
    // --- Global Variables & Elements ---
    const menuItems = document.querySelectorAll('.menu-item');
    const contentSections = document.querySelectorAll('.content-section');
    const globalStatusMessageDiv = document.getElementById('global-status-message');

    // Specific form and status elements
    const ingestForm = document.getElementById('ingestForm');
    const ingestStatusMessageDiv = document.getElementById('ingestStatusMessage');

    const uploadContactsForm = document.getElementById('uploadContactsForm');
    const uploadContactsStatusMessageDiv = document.getElementById('uploadContactsStatusMessage');

    const uploadScrapedDataForm = document.getElementById('uploadScrapedDataForm');
    const uploadScrapedDataStatusMessageDiv = document.getElementById('uploadScrapedDataStatusMessage');

    const whatsappConfigForm = document.getElementById('whatsappConfigForm');
    const whatsappConfigStatusMessageDiv = document.getElementById('whatsappConfigStatusMessage');
    const waAccountIdInput = document.getElementById('waAccountId');
    const waAccountNameInput = document.getElementById('waAccountName');
    const waPhoneNumberIdInput = document.getElementById('waPhoneNumberId');
    const waAccessTokenInput = document.getElementById('waAccessToken');
    const waIsDefaultCheckbox = document.getElementById('waIsDefault');

    const contactsTableBody = document.getElementById('contactsTableBody');
    const contactsStatusMessageDiv = document.getElementById('contactsStatusMessage');
    const refreshContactsButton = document.getElementById('refreshContactsButton');
    const contactSearchInput = document.getElementById('contactSearchInput');


    // --- Helper Function to Display Status Messages ---
    function showStatusMessage(element, message, type = 'info') { // types: info, success, error
        if (element) {
            element.textContent = message;
            element.className = `status-message ${type}`; // Ensure base class is always there
            element.style.display = 'block';
        }
    }
    function clearStatusMessage(element) {
        if (element) {
            element.textContent = '';
            element.style.display = 'none';
        }
    }

    // --- Navigation Logic ---
    function activateSection(targetId) {
        contentSections.forEach(section => section.classList.remove('active'));
        menuItems.forEach(item => item.classList.remove('active'));

        const targetSection = document.getElementById(targetId);
        const targetMenuItem = document.querySelector(`.menu-item[data-target="${targetId}"]`);

        if (targetSection) targetSection.classList.add('active');
        if (targetMenuItem) targetMenuItem.classList.add('active');

        // Load data for section if needed
        if (targetId === 'crm-contacts-content') {
            fetchContacts();
        } else if (targetId === 'whatsapp-config-content') {
            loadWhatsAppConfig();
        }
    }

    menuItems.forEach(item => {
        item.addEventListener('click', (event) => {
            const targetId = item.getAttribute('data-target');
            if (targetId) {
                event.preventDefault();
                activateSection(targetId);
                // Optional: Update URL hash
                // window.location.hash = item.getAttribute('href');
            } else if (item.getAttribute('href') === '#logout') {
                // Handle logout if necessary
                console.log('Logout clicked');
            }
        });
    });

    // Activate default section (CRM Dashboard or first available)
    const defaultActiveMenuItem = document.querySelector('.menu-item.active');
    if (defaultActiveMenuItem) {
        activateSection(defaultActiveMenuItem.getAttribute('data-target'));
    } else if (menuItems.length > 0 && menuItems[0].getAttribute('data-target')) {
        activateSection(menuItems[0].getAttribute('data-target'));
    }


    // --- RAG Knowledge Base Ingestion Logic ---
    if (ingestForm) {
        ingestForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showStatusMessage(ingestStatusMessageDiv, 'Processing RAG data...', 'info');
            const formData = new FormData(ingestForm);
            // Log FormData contents for debugging RAG form
            // for (let [key, value] of formData.entries()) {
            //     if (value instanceof File) { console.log(`Ingest ${key}: ${value.name}`);}
            //     else { console.log(`Ingest ${key}: ${value}`);}
            // }
            try {
                const response = await fetch(`${API_BASE_URL}/ingest`, {
                    method: 'POST',
                    body: formData,
                });
                const result = await response.json();
                if (response.ok && result.status === "success") {
                    showStatusMessage(ingestStatusMessageDiv, result.message || 'Knowledge base updated successfully!', 'success');
                    ingestForm.reset();
                } else {
                    showStatusMessage(ingestStatusMessageDiv, result.detail || result.message || 'Failed to update knowledge base.', 'error');
                }
            } catch (error) {
                console.error('Error submitting RAG ingest form:', error);
                showStatusMessage(ingestStatusMessageDiv, `An error occurred: ${error.message}`, 'error');
            }
        });
    }

    // --- CRM: Upload Contacts (VCF/CSV) ---
    if (uploadContactsForm) {
        uploadContactsForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const fileInput = document.getElementById('contactsFile');
            if (!fileInput.files.length) {
                showStatusMessage(uploadContactsStatusMessageDiv, 'Please select a file to upload.', 'error');
                return;
            }
            showStatusMessage(uploadContactsStatusMessageDiv, 'Uploading contacts file...', 'info');
            const formData = new FormData(uploadContactsForm);
            try {
                const response = await fetch(`${API_BASE_URL}/contacts/upload_vcf_csv`, {
                    method: 'POST',
                    body: formData,
                });
                const result = await response.json();
                if (response.ok) {
                    showStatusMessage(uploadContactsStatusMessageDiv, result.message || 'Contacts processed successfully!', 'success');
                    uploadContactsForm.reset();
                    fetchContacts(); // Refresh contacts list if visible
                } else {
                    showStatusMessage(uploadContactsStatusMessageDiv, result.detail || result.message || 'Failed to upload contacts.', 'error');
                }
            } catch (error) {
                console.error('Error uploading contacts file:', error);
                showStatusMessage(uploadContactsStatusMessageDiv, `An error occurred: ${error.message}`, 'error');
            }
        });
    }

    // --- CRM: Upload Scraped Group Data (CSV) ---
    if (uploadScrapedDataForm) {
        uploadScrapedDataForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const fileInput = document.getElementById('scrapedFile');
            const groupNameInput = document.getElementById('groupNameInput');
            if (!fileInput.files.length || !groupNameInput.value.trim()) {
                showStatusMessage(uploadScrapedDataStatusMessageDiv, 'Please provide a group name and select a file.', 'error');
                return;
            }
            showStatusMessage(uploadScrapedDataStatusMessageDiv, 'Uploading scraped group data...', 'info');
            const formData = new FormData(uploadScrapedDataForm);
             try {
                const response = await fetch(`${API_BASE_URL}/contacts/upload_scraped_group_data`, {
                    method: 'POST',
                    body: formData, // FastAPI will get group_name from FormData
                });
                const result = await response.json();
                if (response.ok) {
                    showStatusMessage(uploadScrapedDataStatusMessageDiv, result.message || 'Scraped data processed!', 'success');
                    uploadScrapedDataForm.reset();
                    fetchContacts(); // Refresh contacts list
                } else {
                    showStatusMessage(uploadScrapedDataStatusMessageDiv, result.detail || result.message || 'Failed to process scraped data.', 'error');
                }
            } catch (error) {
                console.error('Error uploading scraped data:', error);
                showStatusMessage(uploadScrapedDataStatusMessageDiv, `An error occurred: ${error.message}`, 'error');
            }
        });
    }

    // --- CRM: Fetch and Display Contacts ---
    async function fetchContacts(searchTerm = '') {
        if (!contactsTableBody) return;
        showStatusMessage(contactsStatusMessageDiv, 'Loading contacts...', 'info');
        try {
            // TODO: Add search term to API if backend supports it
            const response = await fetch(`${API_BASE_URL}/contacts/?limit=100`); // Add skip/limit later
            if (!response.ok) {
                const errorResult = await response.json();
                throw new Error(errorResult.detail || `Server error: ${response.status}`);
            }
            const contacts = await response.json();
            contactsTableBody.innerHTML = ''; // Clear existing rows
            if (contacts.length === 0) {
                contactsTableBody.innerHTML = '<tr><td colspan="7">No contacts found.</td></tr>';
            } else {
                contacts.forEach(contact => {
                    const row = contactsTableBody.insertRow();
                    row.insertCell().textContent = contact.id;
                    row.insertCell().textContent = contact.phone_number;
                    row.insertCell().textContent = contact.name_from_vcf || 'N/A';
                    row.insertCell().textContent = contact.extracted_name || 'N/A';
                    row.insertCell().textContent = contact.email || 'N/A';
                    row.insertCell().textContent = contact.company || 'N/A';
                    const actionsCell = row.insertCell();
                    // Add action buttons (e.g., view details, edit, delete) later
                    actionsCell.innerHTML = `<button data-id="${contact.id}" class="view-contact-btn">View</button>`;
                });
            }
            clearStatusMessage(contactsStatusMessageDiv);
        } catch (error) {
            console.error('Error fetching contacts:', error);
            showStatusMessage(contactsStatusMessageDiv, `Error loading contacts: ${error.message}`, 'error');
            if (contactsTableBody) contactsTableBody.innerHTML = '<tr><td colspan="7">Error loading contacts.</td></tr>';
        }
    }
    if (refreshContactsButton) {
        refreshContactsButton.addEventListener('click', () => fetchContacts(contactSearchInput.value.trim()));
    }
    if (contactSearchInput) {
        contactSearchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                fetchContacts(contactSearchInput.value.trim());
            }
        });
    }


    // --- WhatsApp Configuration Logic ---
    async function loadWhatsAppConfig() {
        showStatusMessage(whatsappConfigStatusMessageDiv, 'Loading WhatsApp configuration...', 'info');
        try {
            const response = await fetch(`${API_BASE_URL}/whatsapp_accounts/default`);
            if (response.status === 404 || response.status === 200 && !(await response.clone().json())) { // Handle 200 with null body
                showStatusMessage(whatsappConfigStatusMessageDiv, 'No default WhatsApp account configured yet. Please create one.', 'info');
                whatsappConfigForm.reset();
                waAccountIdInput.value = ''; // Ensure ID is cleared for creation
                return;
            }
            if (!response.ok) {
                const errorResult = await response.json();
                throw new Error(errorResult.detail || `Server error: ${response.status}`);
            }
            const config = await response.json();
            if (config) {
                waAccountIdInput.value = config.id;
                waAccountNameInput.value = config.account_name;
                waPhoneNumberIdInput.value = config.phone_number_id;
                waAccessTokenInput.value = config.access_token; // Might want to show '********'
                waIsDefaultCheckbox.checked = config.is_default;
                showStatusMessage(whatsappConfigStatusMessageDiv, 'Configuration loaded.', 'success');
            } else {
                 showStatusMessage(whatsappConfigStatusMessageDiv, 'No default WhatsApp account configured. Please create one.', 'info');
                 whatsappConfigForm.reset(); // Clear form for new entry
                 waAccountIdInput.value = '';
            }
        } catch (error) {
            console.error('Error loading WhatsApp config:', error);
            showStatusMessage(whatsappConfigStatusMessageDiv, `Error loading config: ${error.message}`, 'error');
        }
    }

    if (whatsappConfigForm) {
        whatsappConfigForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            showStatusMessage(whatsappConfigStatusMessageDiv, 'Saving WhatsApp configuration...', 'info');

            const accountId = waAccountIdInput.value;
            const data = {
                account_name: waAccountNameInput.value,
                phone_number_id: waPhoneNumberIdInput.value,
                access_token: waAccessTokenInput.value,
                is_default: waIsDefaultCheckbox.checked,
            };

            let url = `${API_BASE_URL}/whatsapp_accounts/`;
            let method = 'POST';

            if (accountId) { // If ID exists, it's an update
                url = `${API_BASE_URL}/whatsapp_accounts/${accountId}`;
                method = 'PUT';
            }

            try {
                const response = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                const result = await response.json();
                if (response.ok) {
                    showStatusMessage(whatsappConfigStatusMessageDiv, 'WhatsApp configuration saved successfully!', 'success');
                    waAccountIdInput.value = result.id; // Update ID in case it was a new creation
                } else {
                    showStatusMessage(whatsappConfigStatusMessageDiv, result.detail || 'Failed to save configuration.', 'error');
                }
            } catch (error) {
                console.error('Error saving WhatsApp config:', error);
                showStatusMessage(whatsappConfigStatusMessageDiv, `An error occurred: ${error.message}`, 'error');
            }
        });
    }

    // Initial setup if on specific pages (e.g. if page reloads or user lands on a hash URL)
    // The activateSection function handles this now by checking the active menu item.

}); // End DOMContentLoaded
