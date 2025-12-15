const resultsDiv = document.getElementById("results");
const resultsCount = document.getElementById("resultsCount");
const suggestionDiv = document.getElementById("suggestion");

const textInput = document.getElementById("textQuery");
let debounceTimer;

// ------------------ Suggestions (debounced) ------------------
textInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(fetchSuggestion, 300);
});

function setSearchExample(example) {
  textInput.value = example;
  suggestionDiv.innerHTML = "";
  searchText();
}

async function fetchSuggestion() {
  const q = textInput.value.trim();
  if (!q) {
    suggestionDiv.innerHTML = "";
    return;
  }

  try {
    const resp = await fetch(`/suggest?q=${encodeURIComponent(q)}`);
    const data = await resp.json();

    if (data.did_you_mean && data.did_you_mean.toLowerCase() !== q.toLowerCase()) {
      suggestionDiv.innerHTML = `Did you mean: <a href="#" onclick="setSearchExample('${data.did_you_mean}')">${data.did_you_mean}</a>?`;
    } else {
      suggestionDiv.innerHTML = "";
    }
  } catch (err) {
    console.error("Suggestion error:", err);
    suggestionDiv.innerHTML = "";
  }
}

// ------------------ Render Results ------------------
function displayResults(items) {
  resultsDiv.innerHTML = "";
  resultsCount.textContent = `${items.length} ${items.length === 1 ? "item" : "items"}`;

  if (!items.length) {
    resultsDiv.innerHTML = `
      <div class="no-results">
        <i class="fas fa-search"></i>
        <h3>No results found</h3>
        <p>Try different keywords or another image.</p>
      </div>`;
    return;
  }

  items.forEach(item => {
    const div = document.createElement("div");
    div.className = "result";

    // ---- Image ----
    const imgDiv = document.createElement("div");
    imgDiv.className = "result-image";
    const img = document.createElement("img");

    // image_path is stored as absolute/local path (e.g. static/uploads/x.jpg)
    if (item.image_path.startsWith("/static")) {
      img.src = item.image_path;
    } else if (item.image_path.startsWith("static")) {
      img.src = `/${item.image_path}`;
    } else {
      img.src = `/static/uploads/${item.image_path.split("/").pop()}`;
    }

    img.alt = item.item_name || "Furniture item";
    imgDiv.appendChild(img);
    div.appendChild(imgDiv);

    // ---- Info ----
    const info = document.createElement("div");
    info.className = "result-content";
    info.innerHTML = `
      <h3 class="result-title">${item.item_name || ""}</h3>
      <p class="result-description">${item.description || ""}</p>
      <div class="result-price">${item.final_price ?? item.price ?? ""}</div>
      <div class="result-tags">
        ${(item.colors || []).map(c => `<span class="tag">${c}</span>`).join("")}
      </div>
    `;

    div.appendChild(info);
    resultsDiv.appendChild(div);
  });
}

// ------------------ Text Search ------------------
async function searchText() {
  const q = textInput.value.trim();
  if (!q) {
    alert("Enter a text query");
    return;
  }

  suggestionDiv.innerHTML = "";

  try {
    const resp = await fetch(`/search/text?q=${encodeURIComponent(q)}&k=10`);
    if (!resp.ok) {
      const text = await resp.text();
      alert(`Error ${resp.status}: ${text}`);
      return;
    }

    const data = await resp.json();
    displayResults(data.results || []);
  } catch (err) {
    alert("Error fetching results: " + err);
  }
}

// ------------------ Image Search ------------------
async function searchImage() {
  const fileInput = document.getElementById("imageQuery");
  if (!fileInput.files.length) {
    alert("Select an image first");
    return;
  }

  suggestionDiv.innerHTML = "";

  const formData = new FormData();
  formData.append("image", fileInput.files[0]);

  try {
    const resp = await fetch("/search/image?k=10", {
      method: "POST",
      body: formData
    });

    if (!resp.ok) {
      const text = await resp.text();
      alert(`Error ${resp.status}: ${text}`);
      return;
    }

    const data = await resp.json();
    displayResults(data.results || []);
  } catch (err) {
    alert("Error fetching image results: " + err);
  }
}