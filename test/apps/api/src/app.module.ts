import { Module, Type } from '@nestjs/common';
import { HealthController } from './health.controller';
import { isAdminModuleEnabled } from './admin/admin-modules';
import { InstructorAuditController } from './admin/instructor-audit.controller';

const adminControllers: Type<unknown>[] = [];
if (isAdminModuleEnabled('instructor-audit')) {
  adminControllers.push(InstructorAuditController);
}

@Module({
  imports: [],
  controllers: [HealthController, ...adminControllers],
  providers: [],
})
export class AppModule {}
