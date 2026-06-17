// Standard CBSE subjects — mirrors the seeded DB list
export const CBSE_SUBJECTS = [
  // Languages
  'English Core',
  'English Elective',
  'English Language & Literature',
  'Hindi Core',
  'Hindi Elective',
  'Hindi Course A',
  'Hindi Course B',
  'Sanskrit Core',
  'Sanskrit Elective',
  'French',
  'German',
  'Spanish',
  'Tamil',
  'Telugu',
  'Kannada',
  'Malayalam',
  'Marathi',
  'Punjabi',
  'Urdu',
  // Mathematics
  'Mathematics',
  'Mathematics Standard',
  'Mathematics Basic',
  // Sciences
  'Science',
  'Physics',
  'Chemistry',
  'Biology',
  'Biotechnology',
  // Social Sciences
  'Social Science',
  'History',
  'Geography',
  'Political Science',
  'Economics',
  'Sociology',
  'Psychology',
  // Commerce
  'Accountancy',
  'Business Studies',
  // Technology
  'Computer Science',
  'Informatics Practices',
  'Information Technology',
  // Primary
  'Environmental Studies',
  // Vocational / Other
  'Physical Education',
  'Fine Arts',
  'Painting',
  'Music',
  'Home Science',
  'Entrepreneurship',
  'Legal Studies',
];

export const subjectOptions = CBSE_SUBJECTS.map(s => ({ label: s, value: s }));
