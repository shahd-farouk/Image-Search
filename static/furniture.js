// DOM Elements
    const resultsDiv = document.getElementById("results");
    const resultsCount = document.getElementById("resultsCount");
    const suggestionDiv = document.getElementById("suggestion");
    const textInput = document.getElementById("textQuery");
    const imageInput = document.getElementById("imageQuery");
    const imageUploadBtn = document.getElementById("imageUploadBtn");
    const imageIndicator = document.getElementById("imageIndicator");
    const imageName = document.getElementById("imageName");
    const clearImageBtn = document.getElementById("clearImageBtn");

    let debounceTimer;

    // Initialize
    document.addEventListener('DOMContentLoaded', function() {
      imageInput.addEventListener('change', handleImageUpload);
      clearImageBtn.addEventListener('click', clearImage);
      textInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(fetchSuggestion, 300);
      });
    });

    // Handle image upload
    function handleImageUpload() {
      const file = imageInput.files[0];
      if (file) {
        imageUploadBtn.innerHTML = '<i class="fas fa-sync-alt"></i><span>Change Image</span>';
        imageIndicator.classList.add('active');
        
        let fileName = file.name;
        if (fileName.length > 30) {
          fileName = fileName.substring(0, 27) + '...';
        }
        imageName.textContent = fileName;
        
        // Visual feedback
        imageUploadBtn.style.borderColor = 'var(--success)';
        imageUploadBtn.style.background = 'rgba(92, 131, 116, 0.05)';
      }
    }

    // Clear uploaded image
    function clearImage() {
      imageInput.value = '';
      imageIndicator.classList.remove('active');
      imageName.textContent = 'No file selected';
      imageUploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Upload Image</span>';
      imageUploadBtn.style.borderColor = '';
      imageUploadBtn.style.background = '';
      
      if (textInput.value.trim()) {
        textInput.focus();
      }
    }

    // Set search example
    function setSearchExample(example) {
      textInput.value = example;
      clearImage();
      suggestionDiv.innerHTML = "";
      textInput.focus();
      searchText();
    }

    // Suggestion functionality
    async function fetchSuggestion() {
      const q = textInput.value.trim();
      if (!q) {
        suggestionDiv.innerHTML = "";
        return;
      }
      
      try {
        const resp = await fetch(`/suggest?q=${encodeURIComponent(q)}`);
        const data = await resp.json();

        if (data.did_you_mean && data.did_you_mean.length > 0) {
          const filteredSuggestions = data.did_you_mean.filter(
            s => s.toLowerCase() !== q.toLowerCase()
          );

          if (filteredSuggestions.length > 0) {
            suggestionDiv.innerHTML = `
              Did you mean: 
              ${filteredSuggestions
                .map(
                  s => `<a onclick="setSearchExample('${escapeHtml(s)}')">${escapeHtml(s)}</a>`
                )
                .join(", ")}?
            `;
            return;
          }
        }

        suggestionDiv.innerHTML = "";
      } catch (err) {
        console.error("Suggestion error:", err);
        suggestionDiv.innerHTML = "";
      }
    }

    function escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    // Display results
    function displayResults(items) {
      resultsDiv.innerHTML = "";
      resultsCount.textContent = `${items.length} ${items.length === 1 ? "item" : "items"}`;

      if (items.length === 0) {
        resultsDiv.innerHTML = `
          <div class="no-results">
            <i class="fas fa-search"></i>
            <h3>No Results Found</h3>
            <p>Try adjusting your search terms or upload a different image</p>
          </div>`;
        return;
      }

      items.forEach(item => {
        const card = document.createElement("div");
        card.className = "result-card";

        card.innerHTML = `
          <div class="result-image">
            <img src="/static/${item.image_path}" alt="${item.item_name || 'Furniture piece'}" loading="lazy">
          </div>
          <div class="result-content">
            <h3 class="result-name">${escapeHtml(item.item_name || "")}</h3>
            <div class="result-type">${escapeHtml(item.item_type || "")}</div>
            <div class="result-colors">
              ${(item.colors || [])
                .map(color => `<span class="color-tag">${escapeHtml(color)}</span>`)
                .join("")}
            </div>
          </div>
        `;

        resultsDiv.appendChild(card);
      });
    }

    // Search function
    async function searchText() {
      const q = textInput.value.trim();
      const file = imageInput.files[0];
      
      if (file) {
        await searchImage();
      } else if (q) {
        await performTextSearch(q);
      } else {
        // Show subtle visual feedback instead of alert
        textInput.focus();
        textInput.style.borderColor = '#e74c3c';
        setTimeout(() => {
          textInput.style.borderColor = '';
        }, 1500);
        return;
      }
    }

    async function performTextSearch(q) {
      suggestionDiv.innerHTML = "";

      try {
        const resp = await fetch(`/search/text?q=${encodeURIComponent(q)}&k=25`);
        if (!resp.ok) {
          throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        displayResults(data.results || []);
      } catch (err) {
        console.error("Search error:", err);
        suggestionDiv.innerHTML = '<span style="color:#e74c3c">Search failed. Please try again.</span>';
      }
    }

    async function searchImage() {
      const file = imageInput.files[0];
      const q = textInput.value.trim();
      
      if (!file && !q) {
        textInput.focus();
        return;
      }

      suggestionDiv.innerHTML = "";

      const formData = new FormData();
      if (file) formData.append("image", file);
      if (q) formData.append("text", q);

      try {
        const resp = await fetch("/search/image?k=25", {
          method: "POST",
          body: formData
        });

        if (!resp.ok) throw new Error(`Error ${resp.status}`);

        const data = await resp.json();
        displayResults(data.results || []);
      } catch (err) {
        console.error("Image search error:", err);
        suggestionDiv.innerHTML = '<span style="color:#e74c3c">Image search failed. Please try again.</span>';
      }
    }