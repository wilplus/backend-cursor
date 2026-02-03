import { redirect } from "next/navigation";
import AdminShell from "@/components/admin/AdminShell";

// Replace with your admin guard (e.g. check session + admin_users)
async function getAdminSession() {
  // const session = await getServerSession();
  // if (!session?.user?.email) return null;
  // const isAdmin = await checkAdminByEmail(session.user.email);
  // if (!isAdmin) return null;
  // return { email: session.user.email };
  return { email: "admin@example.com" };
}

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getAdminSession();
  if (!session) redirect("/login"); // or /admin/login

  return (
    <AdminShell email={session.email} onLogout={undefined}>
      {children}
    </AdminShell>
  );
}
