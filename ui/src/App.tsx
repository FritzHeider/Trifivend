import { FormEvent, useEffect, useState } from "react";
import { CallRecord, createCall, fetchCalls } from "./api";

export default function App() {
  const [toNumber, setToNumber] = useState("+15555550100");
  const [message, setMessage] = useState("Hi! This is a TriFiVend MVP call.");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [calls, setCalls] = useState<CallRecord[]>([]);

  useEffect(() => {
    loadCalls();
  }, []);

  async function loadCalls() {
    try {
      const records = await fetchCalls();
      setCalls(records);
    } catch (error) {
      console.error(error);
      setErrorMessage("Unable to load call history.");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      const call = await createCall({
        to_number: toNumber,
        message,
      });
      setStatusMessage(`Call queued with status "${call.status}".`);
      setToNumber("+15555550100");
      setMessage("Hi! This is a TriFiVend MVP call.");
      await loadCalls();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setErrorMessage(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main>
      <div className="card">
        <h1>TriFiVend MVP</h1>
        <p>Trigger an outbound call with a short message.</p>
        <form onSubmit={handleSubmit}>
          <label htmlFor="to-number">Phone number</label>
          <input
            id="to-number"
            value={toNumber}
            onChange={(event) => setToNumber(event.target.value)}
            placeholder="+15555550100"
            required
          />

          <label htmlFor="message">Message</label>
          <textarea
            id="message"
            rows={4}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            required
          />

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Sending..." : "Send call"}
          </button>
        </form>

        {statusMessage && <div className="status">✅ {statusMessage}</div>}
        {errorMessage && <div className="status">❌ {errorMessage}</div>}

        <section className="history">
          <h2>Recent calls</h2>
          {calls.length === 0 ? (
            <p>No calls yet.</p>
          ) : (
            <ul>
              {calls.map((call) => (
                <li key={call.id}>
                  <span>
                    <strong>{call.to_number}</strong>
                    <br />
                    <small>{new Date(call.created_at).toLocaleString()}</small>
                  </span>
                  <span className="status-pill">{call.status}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
