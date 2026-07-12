package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.ImportTaskSnapshotEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

/** Persistence access for import-task rollback snapshots. */
@Mapper
public interface ImportTaskSnapshotMapper extends BaseMapper<ImportTaskSnapshotEntity> {
    /** Return the newest canonicalization snapshot for one task. */
    @Select("""
            SELECT * FROM java_import_task_snapshots
            WHERE task_id = #{taskId} AND snapshot_type = 'canonicalization'
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """)
    ImportTaskSnapshotEntity selectLatestByTaskId(String taskId);
}
