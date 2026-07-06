package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.CallbackEventEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 回调事件表访问 Mapper。
 *
 * <p>继承 MyBatis Plus {@link BaseMapper}，提供 {@link CallbackEventEntity} 的基础 CRUD 能力。</p>
 */
@Mapper
public interface CallbackEventMapper extends BaseMapper<CallbackEventEntity> {
}
