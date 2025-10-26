export const API_BASE_URL = "http://localhost:8000";

export type CallRecord = {
  id: string;
  to_number: string;
  message: string;
  status: string;
  provider_sid: string | null;
  created_at: string;
  updated_at: string;
};

export type CreateCallPayload = {
  to_number: string;
  message: string;
};

export async function createCall(payload: CreateCallPayload): Promise<CallRecord> {
  const response = await fetch(`${API_BASE_URL}/calls`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Failed to create call");
  }

  return response.json();
}

export async function fetchCalls(): Promise<CallRecord[]> {
  const response = await fetch(`${API_BASE_URL}/calls`);
  if (!response.ok) {
    throw new Error("Failed to fetch calls");
  }
  const payload = await response.json();
  return payload.calls as CallRecord[];
}
