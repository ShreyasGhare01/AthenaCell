export class ResearchLibrary {
    init() {
        const uploadArea = document.getElementById("uploadArea");
        const fileInput = document.getElementById("fileInput");

        if (!uploadArea || !fileInput) return;

        // Click to upload
        uploadArea.addEventListener("click", () => {
            fileInput.click();
        });

        // Hidden input changed
        fileInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            this.uploadFile(file);
        });

        // Keyboard navigation
        uploadArea.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInput.click();
            }
        });

        // Drag and drop handlers
        uploadArea.addEventListener("dragover", (e) => {
            e.preventDefault();
            uploadArea.classList.add("dragover");
        });

        uploadArea.addEventListener("dragleave", (e) => {
            e.preventDefault();
            uploadArea.classList.remove("dragover");
        });

        uploadArea.addEventListener("drop", (e) => {
            e.preventDefault();
            uploadArea.classList.remove("dragover");
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                this.uploadFile(e.dataTransfer.files[0]);
            }
        });
    }

    uploadFile(file) {
        const formData = new FormData();
        formData.append("file", file);

        fetch("/api/research/upload", {
            method: "POST",
            body: formData
        })
        .then(r => r.json())
        .then(res => {
            const previewBox = document.getElementById("previewBox");
            const previewJson = document.getElementById("previewJson");
            if (previewBox && previewJson) {
                previewBox.style.display = "block";
                previewJson.innerText = JSON.stringify(res.strategy, null, 2);
            }
        })
        .catch(err => {
            alert("Upload failed: " + err);
        });
    }
}

export const researchLibrary = new ResearchLibrary();
