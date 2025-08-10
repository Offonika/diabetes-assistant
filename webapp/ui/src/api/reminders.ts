export interface ReminderPayload {
  type: 'sugar' | 'insulin' | 'meal' | 'medicine';
  title: string;
  time: string;
  interval?: string;
}

const API_BASE = '/api';

export async function updateReminder(id: string, payload: ReminderPayload) {
  const res = await fetch(`${API_BASE}/reminders/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error('Failed to update reminder');
  }
  return res.json();
}

export async function createReminder(payload: ReminderPayload) {
  const res = await fetch(`${API_BASE}/reminders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error('Failed to create reminder');
  }
  return res.json();
}
