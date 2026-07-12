package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.StandardizationBatchItemEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface StandardizationBatchItemMapper extends BaseMapper<StandardizationBatchItemEntity> {
    @Select("SELECT * FROM java_standardization_batch_items WHERE job_id=#{jobId} ORDER BY created_at, id")
    List<StandardizationBatchItemEntity> selectByJobId(String jobId);

    @Select("SELECT * FROM java_standardization_batch_items WHERE input_hash=#{inputHash} AND status='success' ORDER BY finished_at DESC LIMIT 1")
    StandardizationBatchItemEntity selectSuccessfulByInputHash(String inputHash);
}
