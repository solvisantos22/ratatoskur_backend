export type Classroom = {
  id: string;
  name: string;
  join_code: string;
  student_count: number;
};
export type Assignment = {
  id: string;
  class_id: string;
  class_name: string;
  title: string;
  allow_reveal: boolean;
  item_count: number;
  created_at: string;
};
export type Exercise = {
  id: string;
  title: string;
  position: number;
  image_url: string;
};
export type StudentProgress = {
  id: string;
  full_name: string | null;
  completed_count: number;
  attempt_count: number;
  hint_count: number;
  needs_attention: boolean;
  last_activity: string | null;
};
export type Overview = {
  assignment: Assignment;
  items: Exercise[];
  students: StudentProgress[];
  common_errors: { error_type: string; count: number }[];
};
export type Attempt = {
  id: string;
  mode: string;
  verdict: string | null;
  response_type: string | null;
  message_is: string | null;
  created_at: string;
  solution_image_url: string | null;
  solution_page_urls: string[];
};
export type StudentWork = {
  student: { id: string; full_name: string | null };
  assignment: Assignment;
  items: (Exercise & { problem_id: string | null; attempts: Attempt[] })[];
};
export type Me = { id: string; email: string; full_name: string | null };
export function errorLabel(value: string) {
  return (
    (
      {
        sign_error: 'Formerki',
        order_of_operations: 'Röð reikniaðgerða',
        distribution_error: 'Dreifiregla',
        equation_isolation_error: 'Einangrun óþekktrar stærðar',
        fraction_common_denominator_error: 'Samnefnari',
        fraction_simplification_error: 'Stytting brota',
        fraction_arithmetic_error: 'Reikningur með brotum',
      } as Record<string, string>
    )[value] ?? 'Önnur skráð villa'
  );
}
export function studentName(student: { id: string; full_name: string | null }) {
  return student.full_name?.trim() || `Nemandi ${student.id.slice(0, 6)}`;
}
export function when(value: string | null) {
  if (!value) return 'Engin innsending';
  const date = new Date(
    /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`,
  );
  return new Intl.DateTimeFormat('is-IS', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}
export function verdictLabel(value: string | null) {
  return (
    (
      {
        fully_solved: 'Rétt lausn að mati AI',
        fully_correct: 'Rétt lausn að mati AI',
        correct_so_far: 'Rétt svo langt að mati AI',
        incorrect: 'Möguleg villa',
        unclear: 'Óljós rithönd',
      } as Record<string, string>
    )[value ?? ''] ?? 'Ekki metið'
  );
}
export function modeLabel(value: string) {
  return (
    (
      {
        hint: 'Vísbending',
        check_solution: 'Lausn yfirfarin',
        reveal: 'Lausn sýnd',
      } as Record<string, string>
    )[value] ?? 'Svar'
  );
}
