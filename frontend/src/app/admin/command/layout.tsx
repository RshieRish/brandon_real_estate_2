import { CommandShell } from '@/components/command/shell/CommandShell';
import './command-shell.css';

export default function CommandLayout({ children }: { children: React.ReactNode }) {
  return <CommandShell>{children}</CommandShell>;
}
