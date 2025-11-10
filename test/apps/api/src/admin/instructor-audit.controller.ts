import { Controller, Get } from '@nestjs/common';

@Controller('admin/instructor-audit')
export class InstructorAuditController {
  @Get('health')
  healthCheck() {
    return { ok: true };
  }
}
