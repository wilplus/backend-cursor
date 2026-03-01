# Admin link next to logo (artur@willonski.com only)

So that the designated admin can reach the admin panel from the main app, show an **Admin** button next to the logo **only for** `artur@willonski.com`.

## In your main app (student/homework app)

1. In your main layout or header (where the logo lives), get the current user’s email from your auth/session (e.g. Supabase session).
2. Render the Admin link only when that email is `artur@willonski.com`, linking to `/admin`.

### Reference component

Copy **`docs/frontend-admin-panel/components/AdminLink.tsx`** into your main app (e.g. next to the logo in the header):

- It accepts `email` (string | null | undefined).
- It renders nothing for other users and a link to `/admin` for `artur@willonski.com`.

Example usage in your header:

```tsx
import AdminLink from "@/components/AdminLink"; // or your path

// In your header, next to the logo:
<header>
  <Link href="/">… logo …</Link>
  {session?.user?.email && <AdminLink email={session.user.email} />}
  …
</header>
```

No backend change is required; admin routes are already protected by the admin check. This only controls visibility of the link in the main app UI.
