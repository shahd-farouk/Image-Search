const resultsDiv = document.getElementById("results");
const resultsCount = document.getElementById("resultsCount");

function setSearchExample(example) {
  document.getElementById("textQuery").value = example;
  searchText();
}

function displayResults(items) {
  resultsDiv.innerHTML = "";
  resultsCount.textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`;

  if (!items.length) {
    resultsDiv.innerHTML = `<div class="no-results">
      <i class="fas fa-search"></i>
      <h3>No results found</h3>
      <p>Try different keywords or another image.</p>
    </div>`;
    return;
  }

  items.forEach(item => {
    const div = document.createElement("div");
    div.className = "result";

    const imgDiv = document.createElement("div");
    imgDiv.className = "result-image";
    const img = document.createElement("img");

    // Serve from /static
    img.src = item.image_path.startsWith("/static") ? item.image_path : `/static/${item.image_path.split("/").pop()}`;
    img.alt = item.item_name;
    imgDiv.appendChild(img);
    div.appendChild(imgDiv);

    const info = document.createElement("div");
    info.className = "result-content";
    info.innerHTML = `
      <h3 class="result-title">${item.item_name}</h3>
      <p class="result-description">${item.description || ""}</p>
      <div class="result-price">${item.price || ""}</div>
      <div class="result-tags">
        ${(item.colors || []).map(c => `<span class="tag">${c}</span>`).join("")}
      </div>
    `;
    div.appendChild(info);

    resultsDiv.appendChild(div);
  });
}

// Text search
async function searchText() {
  const q = document.getElementById("textQuery").value.trim();
  if (!q) return alert("Enter a text query");

  try {
    const resp = await fetch(`/search/text?q=${encodeURIComponent(q)}&k=10`);
    if (!resp.ok) {
        const text = await resp.text();
        alert("Error: " + resp.status + " - " + text);
        return;
    }
    const data = await resp.json();
    displayResults(data.results);
  } catch (err) {
    alert("Error fetching results: " + err);
  }
}

// Image search
async function searchImage() {
  const fileInput = document.getElementById("imageQuery");
  if (!fileInput.files.length) return alert("Select an image first");

  const formData = new FormData();
  formData.append("image", fileInput.files[0]);

  try {
    const resp = await fetch("/search/image?k=10", { method: "POST", body: formData });
    const data = await resp.json();
    displayResults(data.results);
  } catch (err) {
    alert("Error fetching image results: " + err);
  }
}