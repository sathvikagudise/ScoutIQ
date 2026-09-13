import type { Contact } from "../../api/types";
import { formatDateTime, unknown } from "../../utils/format";
import { Card } from "../ui/Card";
import { VerificationBadge } from "./VerificationBadge";
import "./runs.css";

interface ContactsListProps {
  contacts: Contact[];
}

export function ContactsList({ contacts }: ContactsListProps) {
  if (contacts.length === 0) {
    return (
      <Card className="results-empty">
        <p className="results-empty-mark" aria-hidden="true">
          —
        </p>
        <p className="state-title">No contacts recorded</p>
        <p className="state-body">
          No contact rows were persisted for this run. Contacts are assembled
          only from leader evidence present in researched pages.
        </p>
      </Card>
    );
  }

  return (
    <Card className="results-contacts" raised>
      <ul className="results-contact-list">
        {contacts.map((contact) => (
          <li key={contact.contact_id} className="results-contact">
            <div className="results-contact-main">
              <p className="results-contact-name">{contact.full_name}</p>
              <p className="results-contact-role">{unknown(contact.role)}</p>
            </div>
            <div className="results-contact-meta">
              <span className="mono">{formatDateTime(contact.created_at)}</span>
              <VerificationBadge status={contact.verification_status} />
            </div>
            <p className="results-contact-email">
              {contact.email ? (
                <span className="results-email">{contact.email}</span>
              ) : (
                <span className="results-na">
                  Email not recorded — the backend persists no email address for
                  assembled contacts.
                </span>
              )}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}