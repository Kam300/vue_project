import { z } from 'zod'
import { isDisplayDateValid } from '@/utils/date'
import { isPhoneValid } from '@/utils/phone'

export const memberSchema = z.object({
  firstName: z.string().trim().min(1, 'Введите имя'),
  lastName: z.string().trim().min(1, 'Введите фамилию'),
  patronymic: z.string().trim().optional().nullable(),
  gender: z.enum(['MALE', 'FEMALE'], { error: 'Выберите пол' }),
  birthDate: z
    .string()
    .trim()
    .refine((value) => isDisplayDateValid(value), 'Неверная дата рождения'),
  phoneNumber: z
    .string()
    .trim()
    .optional()
    .nullable()
    .refine((value) => !value || isPhoneValid(value), 'Неверный формат номера телефона'),
  role: z.enum(
    [
      'GRANDFATHER',
      'GRANDMOTHER',
      'FATHER',
      'MOTHER',
      'SON',
      'DAUGHTER',
      'GRANDSON',
      'GRANDDAUGHTER',
      'BROTHER',
      'SISTER',
      'UNCLE',
      'AUNT',
      'NEPHEW',
      'NIECE',
      'OTHER'
    ],
    { error: 'Выберите роль' }
  ),
  maidenName: z.string().trim().optional().nullable(),
  fatherId: z.number().nullable().optional(),
  motherId: z.number().nullable().optional(),
  weddingDate: z
    .string()
    .trim()
    .optional()
    .nullable()
    .refine((value) => !value || isDisplayDateValid(value), 'Неверная дата свадьбы')
})

export type MemberSchemaInput = z.input<typeof memberSchema>
