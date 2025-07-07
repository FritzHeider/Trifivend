 
document.getElementById("recordButton").addEventListener("click", async () => {
  const blob = await recordAudio();

  const formData = new FormData();
  formData.append("file", blob, "user_input.wav");

  const res = await fetch("/transcribe", { method: "POST", body: formData });
  const { text, audio_url } = await res.json();

  document.getElementById("transcript").innerText = text;
  const audio = document.getElementById("botAudio");
  audio.src = audio_url;
  audio.play();
});