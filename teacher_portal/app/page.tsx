'use client';

// Signed student-work URLs must bypass image optimization and shared caches.
/* eslint-disable next/no-img-element */
import Link from 'next/link';

import { useCallback, useEffect, useState, type SubmitEvent } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  Copy,
  ImagePlus,
  LogOut,
  Plus,
  RefreshCw,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { AssignmentPolicy } from './assignment-policy';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Progress } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { api, restoreSession, setToken, logoutSession } from '@/lib/api';
import {
  studentName,
  when,
  verdictLabel,
  modeLabel,
  errorLabel,
  type Classroom,
  type Assignment,
  type Overview,
  type StudentWork,
  type Me,
} from '@/lib/classroom';

function formText(form: FormData, field: string) {
  const value = form.get(field);
  return typeof value === 'string' ? value.trim() : '';
}

function ErrorMessage({ error }: { error: string }) {
  return error ? (
    <p role="alert" className="error-message">
      {error}
    </p>
  ) : null;
}
function Blank({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Empty className="blank">
      <EmptyHeader>
        <BookOpen aria-hidden="true" />
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
function Loading() {
  return (
    <output aria-label="Sæki gögn" className="loading">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-28 w-full" />
    </output>
  );
}

export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [booting, setBooting] = useState(true);
  const [sessionMessage, setSessionMessage] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void (async () => {
      if (await restoreSession()) {
        try {
          const user = await api<Me>('/auth/me');
          if (active) setMe(user);
        } catch {
          /* Login remains available. */
        }
      }
      if (active) setBooting(false);
    })();
    const expired = () => {
      setMe(null);
      setSessionMessage('Innskráning rann út. Skráðu þig inn aftur.');
    };
    window.addEventListener('ratatoskur:session-expired', expired);
    return () => {
      active = false;
      window.removeEventListener('ratatoskur:session-expired', expired);
    };
  }, []);
  async function logout() {
    setLogoutBusy(true);
    try {
      await logoutSession();
      setMe(null);
      setSessionMessage('');
    } catch (error) {
      setSessionMessage((error as Error).message);
    } finally {
      setLogoutBusy(false);
    }
  }
  return (
    <>
      <header className="app-header">
        <Link className="brand" href="/" aria-label="Ratatoskur heim">
          <img src="/ratatoskur.svg" alt="" width="38" height="42" />
          <span>
            Ratatoskur<small>Kennaraborð</small>
          </span>
        </Link>
        {me && (
          <div className="account">
            <span>{me.full_name || me.email}</span>
            <Button variant="ghost" disabled={logoutBusy} onClick={logout}>
              <LogOut />
              Útskrá
            </Button>
          </div>
        )}
      </header>
      <main id="main-content">
        <ErrorMessage error={sessionMessage} />
        {booting ? (
          <Loading />
        ) : me ? (
          <TeacherWorkspace key={me.id} />
        ) : (
          <Login
            onLogin={(user) => {
              setMe(user);
              setSessionMessage('');
            }}
          />
        )}
      </main>
      <footer>Ratatoskur · Kennaraviðmót í þróun</footer>
    </>
  );
}

function Login({ onLogin }: { onLogin: (me: Me) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError('');
    try {
      const response = await api<{ access_token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: formText(values, 'email'),
          password: values.get('password'),
        }),
      });
      setToken(response.access_token);
      onLogin(await api<Me>('/auth/me'));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="login-panel">
      <div className="eyebrow">Fyrir kennara</div>
      <h1>Velkomin aftur</h1>
      <p className="intro">
        Skráðu þig inn með Ratatoskur-aðganginum þínum til að úthluta verkefnum
        og fylgja nemendum eftir.
      </p>
      <form onSubmit={submit} className="form-stack">
        <div>
          <Label htmlFor="email">Netfang</Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            required
          />
        </div>
        <div>
          <Label htmlFor="password">Lykilorð</Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            minLength={8}
            maxLength={128}
          />
        </div>
        <ErrorMessage error={error} />
        <Button type="submit" disabled={busy}>
          {busy ? 'Augnablik…' : 'Skrá inn'}
          <ArrowRight />
        </Button>
      </form>
      <p className="quiet note">
        Kennaraaðgangur er stofnaður og virkjaður af Ratatoskur.
      </p>
    </section>
  );
}

function TeacherWorkspace() {
  const [classes, setClasses] = useState<Classroom[]>([]);
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [assignmentId, setAssignmentId] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [work, setWork] = useState<StudentWork | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [newClass, setNewClass] = useState(false);
  const [newAssignment, setNewAssignment] = useState(false);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const refresh = useCallback(() => {
    setLoading(true);
    setError('');
    setVersion((value) => value + 1);
  }, []);
  const classId = classroom?.id;
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const nextClasses = await api<Classroom[]>('/teacher/classes');
        if (!active) return;
        setClasses(nextClasses);
        if (classId) {
          const next = nextClasses.find((item) => item.id === classId);
          if (next) setClassroom(next);
        }
        if (assignmentId && studentId) {
          const value = await api<StudentWork>(
            `/teacher/assignments/${assignmentId}/students/${studentId}`,
          );
          if (active) setWork(value);
        } else if (assignmentId) {
          const value = await api<Overview>(
            `/teacher/assignments/${assignmentId}`,
          );
          if (active) setOverview(value);
        } else if (classId) {
          const value = await api<Assignment[]>(
            `/teacher/classes/${classId}/assignments`,
          );
          if (active) setAssignments(value);
        }
      } catch (error) {
        if (active) setError((error as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [classId, assignmentId, studentId, version]);
  useEffect(() => {
    const context = (
      document as Document & {
        modelContext?: {
          registerTool: (
            tool: unknown,
            options: { signal: AbortSignal },
          ) => void | Promise<void>;
        };
      }
    ).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try {
      void Promise.resolve(
        context.registerTool(
          {
            name: 'read_teacher_classes',
            description: 'Read the signed-in teacher’s own classrooms.',
            inputSchema: {
              type: 'object',
              properties: {},
              additionalProperties: false,
            },
            annotations: { readOnlyHint: true, untrustedContentHint: true },
            execute: async (input: unknown) => {
              if (
                !input ||
                typeof input !== 'object' ||
                Object.keys(input).length
              )
                throw new Error('Expected an empty object');
              return api<Classroom[]>('/teacher/classes');
            },
          },
          { signal: lifecycle.signal },
        ),
      ).catch(() => {});
    } catch {
      /* Optional browser capability. */
    }
    return () => lifecycle.abort();
  }, []);
  function back() {
    setLoading(true);
    setError('');
    if (studentId) {
      setStudentId(null);
      setWork(null);
    } else if (assignmentId) {
      setAssignmentId(null);
      setOverview(null);
    } else {
      setClassroom(null);
      setAssignments([]);
    }
  }
  async function copyCode() {
    if (!classroom) return;
    try {
      await navigator.clipboard.writeText(classroom.join_code);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      setCopyFailed(true);
    }
  }
  const title = studentId
    ? work
      ? studentName(work.student)
      : 'Vinna nemanda'
    : assignmentId
      ? overview?.assignment.title || 'Verkefnasett'
      : classroom?.name || 'Bekkjarnir þínir';
  return (
    <>
      <nav className="breadcrumb" aria-label="Staðsetning">
        <span>Kennaraborð</span>
        {classroom && (
          <>
            <span>/</span>
            <span>{classroom.name}</span>
          </>
        )}
        {assignmentId && (
          <>
            <span>/</span>
            <span>Verkefnasett</span>
          </>
        )}
      </nav>
      <div className="page-heading">
        <div>
          {classroom && (
            <Button variant="ghost" onClick={back} className="back">
              <ArrowLeft />
              Til baka
            </Button>
          )}
          <h1>{title}</h1>
        </div>
        <div className="actions">
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw />
            Uppfæra
          </Button>
          {!assignmentId && (
            <Button
              onClick={() =>
                classroom ? setNewAssignment(true) : setNewClass(true)
              }
            >
              <Plus />
              {classroom ? 'Nýtt verkefnasett' : 'Nýr bekkur'}
            </Button>
          )}
        </div>
      </div>
      <ErrorMessage error={error} />
      {loading ? (
        <Loading />
      ) : error ? (
        <p className="quiet">
          Gögnin birtast þegar tenging og aðgangur hafa verið staðfest. Veldu
          „Uppfæra“ til að reyna aftur.
        </p>
      ) : studentId && work ? (
        <WorkView work={work} />
      ) : assignmentId && overview ? (
        <AssignmentView
          overview={overview}
          onPolicySaved={refresh}
          onStudent={(id) => {
            setLoading(true);
            setError('');
            setStudentId(id);
            setWork(null);
          }}
        />
      ) : classroom ? (
        <>
          <section className="class-banner">
            <div>
              <span className="eyebrow">Bekkjarkóði</span>
              <div className="join-code">{classroom.join_code}</div>
              <p>
                Nemendur slá kóðann inn undir „Mínir bekkir“ í iPad-appinu.
              </p>
              {copyFailed && (
                <output>
                  Veldu kóðann hér að ofan og afritaðu hann handvirkt.
                </output>
              )}
            </div>
            <div className="actions">
              <span className="count">
                <Users />
                {classroom.student_count} nemendur
              </span>
              <Button variant="outline" onClick={copyCode}>
                {copied ? <Check /> : <Copy />}
                {copied ? 'Afritað' : 'Afrita kóða'}
              </Button>
            </div>
          </section>
          <h2 className="section-title">Verkefnasett</h2>
          {assignments.length ? (
            <div className="card-grid">
              {assignments.map((item) => (
                <article key={item.id} className="assignment-card">
                  <BookOpen className="card-icon" />
                  <p className="quiet">{item.item_count} dæmi</p>
                  <h3>{item.title}</h3>
                  <p className="quiet">{when(item.created_at)}</p>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setLoading(true);
                      setError('');
                      setAssignmentId(item.id);
                      setOverview(null);
                    }}
                  >
                    Skoða framvindu
                    <ArrowRight />
                  </Button>
                </article>
              ))}
            </div>
          ) : (
            <Blank title="Fyrsta verkefnasettið">
              Hladdu inn myndum af dæmum og úthlutaðu þeim til bekkjarins.
            </Blank>
          )}
        </>
      ) : classes.length ? (
        <div className="card-grid">
          {classes.map((item) => (
            <article key={item.id} className="class-card">
              <Users className="card-icon" />
              <h2>{item.name}</h2>
              <p>{item.student_count} nemendur</p>
              <Button
                variant="outline"
                onClick={() => {
                  setLoading(true);
                  setError('');
                  setClassroom(item);
                  setCopied(false);
                }}
              >
                Opna bekk
                <ArrowRight />
              </Button>
            </article>
          ))}
        </div>
      ) : (
        <Blank title="Byrjum á einum bekk">
          Stofnaðu bekk og deildu bekkjarkóðanum með nemendum. Síðan geturðu
          úthlutað fyrstu dæmunum.
        </Blank>
      )}
      <CreateClass
        open={newClass}
        onOpenChange={setNewClass}
        onCreated={(item) => {
          setLoading(true);
          setError('');
          setClassroom(item);
          refresh();
        }}
      />
      {classroom && (
        <CreateAssignment
          open={newAssignment}
          classroom={classroom}
          onOpenChange={setNewAssignment}
          onCreated={(item) => {
            setLoading(true);
            setError('');
            setAssignmentId(item.id);
            refresh();
          }}
        />
      )}
    </>
  );
}

function CreateClass({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  onCreated: (item: Classroom) => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = formText(new FormData(event.currentTarget), 'name');
    if (!name) return;
    setBusy(true);
    setError('');
    try {
      const item = await api<Classroom>('/teacher/classes', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });
      onOpenChange(false);
      onCreated(item);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) {
          onOpenChange(value);
          setError('');
        }
      }}
    >
      <DialogContent className="form-dialog">
        <DialogHeader>
          <DialogTitle>Nýr bekkur</DialogTitle>
          <DialogDescription>
            Gefðu bekknum nafn sem nemendur þekkja.
          </DialogDescription>
        </DialogHeader>
        <form className="form-stack" onSubmit={submit}>
          <Label htmlFor="class-name">Heiti bekkjar</Label>
          <Input
            id="class-name"
            name="name"
            placeholder="T.d. 8. A — stærðfræði"
            maxLength={128}
            required
          />
          <ErrorMessage error={error} />
          <Button type="submit" disabled={busy}>
            {busy ? 'Stofna bekk…' : 'Stofna bekk'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CreateAssignment({
  open,
  classroom,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  classroom: Classroom;
  onOpenChange: (value: boolean) => void;
  onCreated: (item: Assignment) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [allowReveal, setAllowReveal] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (
      !files.length ||
      files.length > 12 ||
      files.some((file) => file.size > 7 * 1024 * 1024) ||
      files.reduce((sum, file) => sum + file.size, 0) > 30 * 1024 * 1024
    ) {
      setError('Veldu 1–12 myndir, að hámarki 7 MB hver og 30 MB samtals.');
      return;
    }
    const values = new FormData(event.currentTarget);
    const body = new FormData();
    const title = formText(values, 'title');
    if (!title) {
      setError('Verkefnasettið þarf heiti.');
      return;
    }
    body.set('title', title);
    body.set('allow_reveal', String(allowReveal));
    files.forEach((file) => body.append('images', file));
    setBusy(true);
    try {
      const item = await api<Assignment>(
        `/teacher/classes/${classroom.id}/assignments`,
        { method: 'POST', body },
      );
      setFiles([]);
      setAllowReveal(false);
      onOpenChange(false);
      onCreated(item);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) {
          onOpenChange(value);
          setError('');
          if (!value) {
            setFiles([]);
            setAllowReveal(false);
          }
        }
      }}
    >
      <DialogContent className="form-dialog wide">
        <DialogHeader>
          <DialogTitle>Nýtt verkefnasett</DialogTitle>
          <DialogDescription>
            Úthluta til {classroom.name}. Hver mynd verður eitt dæmi.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="form-stack">
          <div>
            <Label htmlFor="assignment-title">Heiti verkefnasetts</Label>
            <Input
              name="title"
              id="assignment-title"
              required
              maxLength={255}
              placeholder="T.d. Jöfnur — fyrsta æfing"
            />
          </div>
          <div>
            <div className="policy-choice">
              <Label htmlFor="new-assignment-allow-reveal">Leyfa fullar lausnir</Label>
              <Switch
                id="new-assignment-allow-reveal"
                checked={allowReveal}
                onCheckedChange={setAllowReveal}
                disabled={busy}
                aria-describedby="new-assignment-policy-explanation"
              />
            </div>
            <p id="new-assignment-policy-explanation" className="quiet">
              Vísbendingar og yfirferð eru alltaf í boði. Þú getur breytt þessu
              síðar í verkefnasettinu.
            </p>
          </div>
          <div className="upload-area">
            <ImagePlus aria-hidden="true" />
            <Label htmlFor="exercise-images">Myndir af dæmum</Label>
            <p>PNG eða JPG · 1–12 myndir · mest 7 MB hver, 30 MB samtals</p>
            <Input
              id="exercise-images"
              type="file"
              accept="image/png,image/jpeg"
              multiple
              onChange={(event) =>
                setFiles(Array.from(event.target.files || []))
              }
            />
          </div>
          {files.length > 0 && (
            <ol className="file-list">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`}>
                  <span>
                    {index + 1}. {file.name}
                  </span>
                  <span>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                </li>
              ))}
            </ol>
          )}
          <p className="quiet">
            Dæmin birtast strax hjá nemendum í bekknum þegar þú úthlutar.
          </p>
          <ErrorMessage error={error} />
          <Button type="submit" disabled={busy || !files.length}>
            {busy ? 'Hleð inn og úthluta…' : 'Úthluta til bekkjar'}
            <ArrowRight />
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AssignmentView({
  overview,
  onStudent,
  onPolicySaved,
}: {
  overview: Overview;
  onStudent: (id: string) => void;
  onPolicySaved: () => void;
}) {
  const attention = overview.students.filter(
    (student) => student.needs_attention,
  ).length;
  const submitted = overview.students.filter(
    (student) => student.attempt_count > 0 || (student.submission_count ?? 0) > 0,
  ).length;
  return (
    <>
      <div className="stats-grid">
        <div>
          <span>Dæmi í settinu</span>
          <strong>{overview.items.length}</strong>
        </div>
        <div>
          <span>Hafa sent inn</span>
          <strong>
            {submitted}
            <small> / {overview.students.length}</small>
          </strong>
        </div>
        <div className={attention ? 'attention-stat' : ''}>
          <span>Tillaga að yfirferð</span>
          <strong>
            {attention}
            <small> nemendur</small>
          </strong>
        </div>
      </div>
      <AssignmentPolicy
        key={`${overview.assignment.id}-${overview.assignment.allow_reveal}`}
        assignment={overview.assignment}
        onSaved={onPolicySaved}
      />
      <section className="surface">
        <h2>Framvinda nemenda</h2>
        <p className="quiet">
          Framvinda telur dæmi sem AI hefur metið að fullu rétt við yfirferð.
          Skil telja dæmi sem nemandinn hefur skilað beint til kennara. Skil
          staðfesta ekki rétta lausn; framvinda er ekki einkunn eða staðfest hæfnimat.
        </p>
        {overview.students.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nemandi</TableHead>
                <TableHead>Framvinda</TableHead>
                <TableHead>Skil</TableHead>
                <TableHead>AI-beiðnir</TableHead>
                <TableHead>Vísbendingar</TableHead>
                <TableHead>Staða</TableHead>
                <TableHead>
                  <span className="sr-only">Opna úrlausnir</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {overview.students.map((student) => (
                <TableRow key={student.id}>
                  <TableCell className="student-cell">
                    {studentName(student)}
                    <small>{when(student.last_activity)}</small>
                  </TableCell>
                  <TableCell>
                    <div className="progress-cell">
                      <span>
                        {student.completed_count} / {overview.items.length}
                      </span>
                      <Progress
                        aria-label={`Framvinda ${studentName(student)}`}
                        value={
                          overview.items.length
                            ? (student.completed_count /
                                overview.items.length) *
                              100
                            : 0
                        }
                      />
                    </div>
                  </TableCell>
                  <TableCell>{student.submitted_item_count ?? 0} / {overview.items.length}</TableCell>
                  <TableCell>{student.attempt_count}</TableCell>
                  <TableCell>{student.hint_count}</TableCell>
                  <TableCell>
                    <span
                      className={`status ${student.needs_attention ? 'attention' : ''}`}
                    >
                      {student.needs_attention
                        ? 'Skoða nánar'
                        : (student.submission_count ?? 0) > 0
                          ? 'Skilað til kennara'
                          : student.attempt_count
                            ? 'Vinna hafin'
                            : 'Engin innsending'}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      onClick={() => onStudent(student.id)}
                      aria-label={`Skoða vinnu ${studentName(student)}`}
                    >
                      Skoða
                      <ArrowRight />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <Blank title="Bíður eftir nemendum">
            Nemendur birtast hér þegar þeir ganga í bekkinn með bekkjarkóðanum.
          </Blank>
        )}
        <p className="quiet note">
          „Skoða nánar“ bendir á mögulega villu eða óljósa rithönd sem ekki
          hefur verið fylgt eftir með réttri yfirferð. Kennari metur hvort
          nemandi þarf aðstoð.
        </p>
      </section>
      <div className="detail-columns">
        <section className="surface">
          <h2>Dæmin í settinu</h2>
          <div className="exercise-grid">
            {overview.items.map((item) => (
              <figure key={item.id}>
                <a href={item.image_url} target="_blank" rel="noreferrer">
                  <img src={item.image_url} alt={item.title} loading="lazy" />
                </a>
                <figcaption>
                  {item.position + 1}. {item.title}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
        <section className="surface">
          <h2>Villumynstur úr innsendingum</h2>
          <p className="quiet">
            Sjálfvirk flokkun úr þessu verkefnasetti. Sama villa getur komið
            fyrir í fleiri en einni innsendingu.
          </p>
          {overview.common_errors.length ? (
            <ul className="error-patterns">
              {overview.common_errors.map((item) => (
                <li key={item.error_type}>
                  <span>{errorLabel(item.error_type)}</span>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-note">Engin villumynstur hafa verið skráð.</p>
          )}
        </section>
      </div>
    </>
  );
}

function WorkView({ work }: { work: StudentWork }) {
  return (
    <>
      <p className="intro">{work.assignment.title} · Skil og AI-svör</p>
      {work.items.map((item) => (
        <section key={item.id} className="surface work-item">
          <div className="exercise-original">
            <span className="eyebrow">Dæmi {item.position + 1}</span>
            <h2>{item.title}</h2>
            <a href={item.image_url} target="_blank" rel="noreferrer">
              <img src={item.image_url} alt={`Dæmatexti: ${item.title}`} />
            </a>
          </div>
          <div className="attempts">
            <h3>Skil til kennara</h3>
            <p className="quiet">Afrit af vinnu við skil. Síðari breytingar á tæki nemandans birtast þegar nemandinn skilar aftur. Skil hafa ekki verið metin af AI.</p>
            {item.submissions?.length ? (
              item.submissions.map((submission, index) => (
                <article className="attempt" key={submission.id}>
                  <div className="attempt-heading">
                    <strong>Skil {index + 1} · {submission.page_count === 1 ? '1 blað' : `${submission.page_count} blöð`}</strong>
                    <time dateTime={submission.created_at}>{when(submission.created_at)}</time>
                  </div>
                  <div className="handwriting-pages">
                    {submission.solution_page_urls.map((url, page) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        <img src={url} loading="lazy" alt={`Skil ${index + 1}, handskrifuð úrlausn, síða ${page + 1}`} />
                      </a>
                    ))}
                  </div>
                </article>
              ))
            ) : <p className="empty-note">Engin bein skil til kennara enn.</p>}
            <h3>AI-beiðnir og svör</h3>
            {!item.attempts.length ? (
              <Blank title="Engin AI-beiðni enn">
                Hér birtast vísbendingar og yfirferð ásamt handskriftinni sem
                nemandinn sendi með AI-beiðninni.
              </Blank>
            ) : (
              item.attempts.map((attempt, index) => (
                <article className="attempt" key={attempt.id}>
                  <div className="attempt-heading">
                    <strong>
                      {index + 1}. {modeLabel(attempt.mode)}
                    </strong>
                    <time>{when(attempt.created_at)}</time>
                  </div>
                  <span
                    className={`status ${attempt.verdict === 'incorrect' || attempt.verdict === 'unclear' ? 'attention' : ''}`}
                  >
                    {verdictLabel(attempt.verdict)}
                  </span>
                  <div className="handwriting-pages">
                    {(attempt.solution_page_urls?.length
                      ? attempt.solution_page_urls
                      : attempt.solution_image_url
                        ? [attempt.solution_image_url]
                        : []
                    ).map((url, page) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        <img
                          src={url}
                          loading="lazy"
                          alt={`Handskrifuð úrlausn, síða ${page + 1}`}
                        />
                      </a>
                    ))}
                  </div>
                  {!attempt.solution_image_url &&
                    !attempt.solution_page_urls?.length && (
                      <p className="quiet">Mynd af úrlausn er ekki tiltæk.</p>
                    )}
                  <div className="ai-response">
                    <span className="eyebrow">Svar Ratatosks</span>
                    <p>{attempt.message_is || 'Ekkert textasvar var skráð.'}</p>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      ))}
    </>
  );
}
