package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.StandardizationBatchJobEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface StandardizationBatchJobMapper extends BaseMapper<StandardizationBatchJobEntity> {
    @Select("SELECT * FROM java_standardization_batch_jobs WHERE task_id=#{taskId} AND status IN ('queued','running','cancelling') ORDER BY created_at DESC LIMIT 1")
    StandardizationBatchJobEntity selectActiveByTaskId(String taskId);

    @Select("SELECT * FROM java_standardization_batch_jobs WHERE task_id=#{taskId} AND id=#{jobId}")
    StandardizationBatchJobEntity selectByTaskAndId(String taskId, String jobId);
}
