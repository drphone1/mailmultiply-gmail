document.addEventListener('DOMContentLoaded', () => {
    const adminForm = document.getElementById('ingestForm');
    const statusMessageDiv = document.getElementById('statusMessage');

    const chatForm = document.getElementById('chatForm');
    const userInput = document.getElementById('userInput');
    const chatMessagesDiv = document.getElementById('chatMessages');

    // --- Admin Page Logic ---
    if (adminForm) {
        adminForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (statusMessageDiv) {
                statusMessageDiv.textContent = 'Processing...';
                statusMessageDiv.className = 'status-message loading'; // Add class for styling
            }

            const formData = new FormData(adminForm);
            const files = adminForm.querySelector('input[type="file"]').files;
            const url = adminForm.querySelector('input[type="text"]').value;

            if (files.length === 0 && !url.trim()) {
                if (statusMessageDiv) {
                    statusMessageDiv.textContent = 'Please select files or enter a URL.';
                    statusMessageDiv.className = 'status-message error';
                }
                return;
            }

            // Log FormData contents for debugging
            // for (let [key, value] of formData.entries()) {
            //     if (value instanceof File) {
            //         console.log(`${key}: ${value.name}, ${value.size} bytes`);
            //     } else {
            //         console.log(`${key}: ${value}`);
            //     }
            // }


            try {
                // IMPORTANT: Replace with your actual backend URL if different
                const response = await fetch('http://localhost:8000/ingest', {
                    method: 'POST',
                    body: formData, // FormData handles multipart/form-data automatically
                    // headers: { 'Content-Type': 'multipart/form-data' } // Not needed with FormData
                });

                const result = await response.json();

                if (statusMessageDiv) {
                    statusMessageDiv.textContent = result.message || JSON.stringify(result);
                    if (response.ok && result.status === "success") {
                        statusMessageDiv.className = 'status-message success';
                        adminForm.reset(); // Clear the form on success
                    } else {
                        statusMessageDiv.className = 'status-message error';
                    }
                }
            } catch (error) {
                console.error('Error submitting ingest form:', error);
                if (statusMessageDiv) {
                    statusMessageDiv.textContent = `An error occurred: ${error.message || 'Network error'}`;
                    statusMessageDiv.className = 'status-message error';
                }
            }
        });
    }

    // --- Chat Page Logic ---
    if (chatForm && userInput && chatMessagesDiv) {
        // Display initial bot message if desired
        // addMessageToChat("Hello! How can I help you today?", "bot");

        chatForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const messageText = userInput.value.trim();

            if (messageText) {
                addMessageToChat(messageText, 'user');
                userInput.value = ''; // Clear input field

                showTypingIndicator();

                try {
                    // IMPORTANT: Replace with your actual backend URL if different
                    const response = await fetch('http://localhost:8000/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ query: messageText }),
                    });

                    removeTypingIndicator();

                    if (!response.ok) {
                        const errorResult = await response.json();
                        throw new Error(errorResult.detail || `Server error: ${response.status}`);
                    }

                    const result = await response.json();
                    addMessageToChat(result.response, 'bot');

                } catch (error) {
                    removeTypingIndicator();
                    console.error('Error sending chat message:', error);
                    addMessageToChat(`Error: ${error.message || 'Could not connect to the AI agent.'}`, 'bot', true);
                }
            }
        });
    }

    function addMessageToChat(text, sender, isError = false) {
        if (!chatMessagesDiv) return;

        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', `${sender}-message`);
        if (isError) {
            messageDiv.classList.add('error'); // You can style .bot-message.error specifically if needed
        }

        const p = document.createElement('p');
        p.textContent = text;
        messageDiv.appendChild(p);

        chatMessagesDiv.appendChild(messageDiv);
        chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight; // Scroll to the bottom
    }

    let typingIndicator;
    function showTypingIndicator() {
        if (!chatMessagesDiv) return;
        if (typingIndicator) return; // Avoid multiple indicators

        typingIndicator = document.createElement('div');
        typingIndicator.classList.add('message', 'bot-message', 'typing');
        const p = document.createElement('p');
        p.textContent = 'AI Agent is typing...';
        typingIndicator.appendChild(p);

        chatMessagesDiv.appendChild(typingIndicator);
        chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
    }

    function removeTypingIndicator() {
        if (typingIndicator) {
            typingIndicator.remove();
            typingIndicator = null;
        }
    }
});
